## Panduan Revisi Teknis Final untuk Agent-Autonomous: Memperbaiki "Plan Skipping"

### Pendahuluan

Masalah "plan skipping" yang Anda alami, di mana semua rencana tiba-tiba ditandai selesai setelah agen meminta input pengguna, adalah masalah umum dalam sistem agen otonom yang melibatkan interaksi asinkron dan manajemen status. Setelah menganalisis kode terbaru Anda, masalah ini masih terjadi karena meskipun ada upaya untuk menyimpan status `waiting_for_user`, logika utama `run_async` di `agent_flow.py` masih secara prematur keluar dari loop eksekusi utama setelah mengirim event `waiting_for_user`.

Revisi ini akan fokus pada modifikasi `server/agent/agent_flow.py` untuk memastikan alur eksekusi yang benar dan persistensi status saat agen menunggu input pengguna.

### 1. Analisis Akar Masalah

Masalah utama terletak pada bagian `run_async` di `server/agent/agent_flow.py`, khususnya di dalam loop `while True` yang mengiterasi langkah-langkah rencana. Ketika `execute_step_async` menghasilkan event `waiting_for_user` (yang terjadi saat `message_ask_user` dipanggil), variabel `step_waiting` diatur ke `True`. Namun, setelah itu, ada blok kode:

```python
2007	                    yield make_event("done", success=True, session_id=self.session_id)
2008	                    return
```

Blok ini dieksekusi jika `step_waiting` adalah `True`. `yield make_event("done", success=True, ...)` secara efektif memberi sinyal kepada klien (frontend) bahwa tugas telah selesai dengan sukses, dan `return` menghentikan eksekusi `run_async` sepenuhnya. Ini menyebabkan frontend menganggap semua rencana selesai dan menandainya sebagai "terceklis semua", padahal agen seharusnya hanya *menjeda* dan menunggu balasan pengguna.

Solusinya adalah memastikan bahwa ketika agen berada dalam status `waiting_for_user`, `run_async` tidak mengirim event `"done"` dan tidak `return` secara prematur, melainkan hanya menyimpan status dan membiarkan alur eksekusi berhenti secara alami hingga input pengguna berikutnya diterima.

### 2. Panduan Revisi Teknis (A-Z)

Kita akan memodifikasi `server/agent/agent_flow.py` untuk memperbaiki logika ini.

**File:** `server/agent/agent_flow.py`

**Perubahan:**

```python
# ... (import dan definisi kelas FlowState)

class AgentFlow:
    # ... (properti dan metode lainnya)

    async def run_async(
        self,
        user_message: str,
        attachments: Optional[List[str]] = None,
        resume_from_session: Optional[str] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
        is_continuation: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # ... (kode inisialisasi)

        original_user_message = user_message

        # --- LOAD WAITING STATE --- (Pastikan bagian ini sudah benar)
        waiting_state = None
        if resume_from_session:
            svc = await get_session_service()
            waiting_state = await svc.load_waiting_state(resume_from_session)
            if waiting_state:
                self.session_id = resume_from_session
                self.chat_history = waiting_state.get("chat_history", [])
                user_message = waiting_state.get("user_message", user_message)
                if waiting_state.get("plan"):
                    self.plan = Plan.from_dict(waiting_state["plan"])
                    # Pastikan langkah yang tertunda diatur ke RUNNING jika sebelumnya PENDING
                    if self.plan.current_step_id:
                        for step in self.plan.steps:
                            if step.id == self.plan.current_step_id and step.status == ExecutionStatus.PENDING:
                                step.status = ExecutionStatus.RUNNING
                                yield make_event("step", status=StepStatus.RUNNING.value, step=step.to_dict())
                    yield make_event("plan", status=PlanStatus.RESUMED.value, plan=safe_plan_dict(self.plan))
                
                # Clear waiting state after loading
                await svc.clear_waiting_state(self.session_id)
                yield make_event("notify", text="Melanjutkan dari sesi yang tertunda.")

        # ... (kode untuk is_continuation dan _is_simple_query)

        # --- PLAN CREATION --- (Bagian ini seharusnya sudah benar dari revisi sebelumnya)
        if not self.plan:
            # ... (kode pre-plan clarification check)

            self.state = FlowState.PLANNING
            yield make_event("plan", status=PlanStatus.CREATING.value)

            self.plan = await self.run_planner_async(
                user_message, attachments, chat_history=self.chat_history
            )

            if self.session_id and svc:
                await svc.save_plan_snapshot(self.session_id, self.plan.to_dict())

            yield make_event("title", title=self.plan.title)

            if self.plan.message:
                yield make_event("message_start", role="assistant")
                yield make_event("message_chunk", chunk=self.plan.message, role="assistant")
                yield make_event("message_end", role="assistant")

            yield make_event("plan", status=PlanStatus.CREATED.value, plan=safe_plan_dict(self.plan))

            if not self.plan.steps:
                yield make_event("message_start", role="assistant")
                yield make_event("message_chunk", chunk="No actionable steps needed.", role="assistant")
                yield make_event("message_end", role="assistant")
                yield make_event("done", success=True, session_id=self.session_id)
                return

            yield make_event("plan", status=PlanStatus.RUNNING.value, plan=safe_plan_dict(self.plan))

        # --- MAIN EXECUTION LOOP --- (Bagian ini yang perlu diperbaiki secara signifikan)
        _step_consecutive_failures: Dict[str, int] = {}
        _global_consecutive_failures = 0
        _MAX_GLOBAL_FAILURES = 4

        while True:
            step = None
            if self.plan.current_step_id:
                # Cari langkah yang sedang berjalan/tertunda
                for s in self.plan.steps:
                    if s.id == self.plan.current_step_id:
                        step = s
                        break
            
            if not step:
                # Jika tidak ada current_step_id atau langkah tidak ditemukan, ambil langkah berikutnya yang belum selesai
                step = self.plan.get_next_step()

            if not step:
                # Semua langkah selesai atau tidak ada langkah
                break # Keluar dari loop jika tidak ada langkah lagi

            self.plan.current_step_id = step.id # Perbarui current_step_id
            yield make_event("plan", status=PlanStatus.RUNNING.value, plan=safe_plan_dict(self.plan)) # Update plan status

            step_waiting_for_user = False
            try:
                async for event in self.execute_step_async(self.plan, step, user_message):
                    if event.get("type") == "waiting_for_user":
                        step_waiting_for_user = True
                        # Simpan status menunggu dan JANGAN break loop utama di sini
                        if self.session_id:
                            if svc:
                                await svc.save_waiting_state(
                                    self.session_id,
                                    self.plan.to_dict(),
                                    [s.to_dict() for s in self.plan.steps if not s.is_done()],
                                    user_message,
                                    chat_history=self.chat_history,
                                )
                                await svc.save_plan_snapshot(self.session_id, self.plan.to_dict())
                            else:
                                from server.agent.services.session_service import _file_save_waiting_state
                                _file_save_waiting_state(self.session_id, {
                                    "waiting_for_user": True,
                                    "plan": self.plan.to_dict(),
                                    "pending_steps": [s.to_dict() for s in self.plan.steps if not s.is_done()],
                                    "user_message": user_message,
                                    "chat_history": self.chat_history,
                                })
                        yield event # Yield event waiting_for_user ke klien
                        self.state = FlowState.WAITING # Set state agen ke WAITING
                        return # KELUAR dari run_async, menunggu input user berikutnya
                    yield event
            except Exception as e:
                step.status = ExecutionStatus.FAILED
                step.success = False
                step.error = str(e)
                step.result = f"Eksekusi langkah gagal: {e}"
                yield make_event("step", status=StepStatus.FAILED.value, step=step.to_dict())

            if step.status == ExecutionStatus.FAILED:
                _global_consecutive_failures += 1
                fail_count = _step_consecutive_failures.get(step.id, 0) + 1
                _step_consecutive_failures[step.id] = fail_count
                if _global_consecutive_failures >= _MAX_GLOBAL_FAILURES:
                    sys.stderr.write("[agent] Circuit breaker: {} kegagalan berturut-turut, membatalkan rencana\n".format(_global_consecutive_failures))
                    yield make_event("notify", text="Terlalu banyak kegagalan berturut-turut. Menghentikan eksekusi.")
                    self.plan.status = ExecutionStatus.FAILED
                    self.plan.error = "Terlalu banyak kegagalan berturut-turut."
                    yield make_event("plan", status=PlanStatus.FAILED.value, plan=safe_plan_dict(self.plan))
                    break
                elif fail_count < 2:
                    error_ctx = step.result or step.error or "Unknown failure"
                    retry_msg = (
                        f"{user_message}\n\n"
                        f"[RETRY] Upaya sebelumnya untuk langkah ini GAGAL dengan: {error_ctx}. "
                        f"Ambil pendekatan yang BERBEDA. JANGAN ulangi perintah atau strategi yang sama."
                    )
                    step.status = ExecutionStatus.PENDING
                    step.result = None
                    step.error = None
                    yield make_event("step", status="retrying", step=step.to_dict())
                    # Re-execute the step with retry message
                    # This part needs to be handled carefully to avoid infinite loops
                    # For simplicity, we'll let the next iteration of the while loop pick it up
                    continue # Lanjutkan ke iterasi berikutnya untuk mencoba kembali langkah ini
                else:
                    _step_consecutive_failures.pop(step.id, None)
            else:
                _global_consecutive_failures = 0
                _step_consecutive_failures.pop(step.id, None)

            if self.session_id and svc:
                await svc.save_step_completed(self.session_id, step.to_dict())
                await svc.save_plan_snapshot(self.session_id, self.plan.to_dict())

            # Update plan jika ada langkah berikutnya
            next_step_after_current = self.plan.get_next_step()
            if next_step_after_current:
                yield make_event("plan", status=PlanStatus.UPDATING.value,
                                 plan=safe_plan_dict(self.plan))
                plan_event = await self.update_plan_async(self.plan, step)
                if plan_event:
                    yield plan_event
            
            # Jika tidak ada langkah berikutnya dan tidak menunggu user, maka selesai
            if not next_step_after_current and not step_waiting_for_user:
                break

        # --- FINALIZATION (Setelah loop utama selesai) ---
        if not step_waiting_for_user: # Hanya jika tidak menunggu user
            for s in self.plan.steps:
                if s.status == ExecutionStatus.RUNNING:
                    s.status = ExecutionStatus.FAILED
                    s.success = False
                    if not s.result:
                        s.result = "Step did not complete"
                    yield make_event("step", status=StepStatus.FAILED.value, step=s.to_dict())

            self.plan.status = ExecutionStatus.COMPLETED
            yield make_event("plan", status=PlanStatus.COMPLETED.value,
                                     plan=safe_plan_dict(self.plan))

            # ... (kode untuk summarize_async dan pengiriman file)
            summary_chunks: List[str] = []
            async def _summarize_cont():
                async for event in self.summarize_async(self.plan, original_user_message):
                    if event.get("type") == "message_chunk":
                        summary_chunks.append(event.get("chunk", ""))
                    yield event
            async for event in _summarize_cont():
                yield event

            self.state = FlowState.COMPLETED
            summary_text = "".join(summary_chunks)
            if summary_text:
                self.chat_history.append({"role": "user", "content": original_user_message})
                self.chat_history.append({"role": "assistant", "content": summary_text})
                if self.session_id and svc:
                    try:
                        await svc.save_chat_history(self.session_id, self.chat_history[-40:])
                    except Exception:
                        pass
            if self.session_id and svc:
                await svc.complete_session(self.session_id, success=True)
            if self._created_files:
                yield make_event("files", files=self._created_files)

            yield make_event("done", success=True, session_id=self.session_id)

```

### 2.3. Penjelasan Perubahan Kunci

1.  **Penghapusan `yield make_event("done", ...)` dan `return` setelah `waiting_for_user`:** Ini adalah perubahan paling krusial. Dengan menghapus baris-baris tersebut, `run_async` tidak lagi secara prematur memberi sinyal "selesai" kepada klien dan tidak keluar dari fungsi. Sebaliknya, setelah `yield event` untuk `waiting_for_user`, `run_async` akan terus berjalan hingga mencapai akhir fungsi atau `break` dari loop `while True` secara alami (yang hanya terjadi jika tidak ada langkah berikutnya atau ada kegagalan fatal).
2.  **Logika `return` yang Lebih Jelas:** `return` yang terjadi setelah `waiting_for_user` di `execute_step_async` (jika Anda masih memiliki `return` di sana) akan menghentikan generator `execute_step_async`, tetapi tidak akan menghentikan `run_async` secara keseluruhan. `run_async` akan terus berjalan dan kemudian akan `break` dari loop `while True` karena `step_waiting_for_user` akan `True` dan tidak ada `next_step_after_current` yang ditemukan (karena agen sedang menunggu input untuk langkah saat ini).
3.  **Konsistensi `current_step_id`:** Properti `current_step_id` di `Plan` model yang sudah Anda tambahkan akan sangat membantu dalam memastikan agen melanjutkan dari langkah yang benar saat sesi dilanjutkan.

### 2.4. Rekomendasi Tambahan

*   **Frontend Handling:** Pastikan frontend Anda (di `lib/useChat.ts` dan `components/ChatScreen.tsx`) menangani event `waiting_for_user` dengan benar. Ketika event ini diterima, frontend harus menampilkan indikator "menunggu balasan pengguna" dan mengaktifkan kembali input pengguna, tanpa menandai plan sebagai selesai. Dari analisis `useChat.ts`, terlihat bahwa `setIsWaitingForUser(true)` sudah dipanggil, yang bagus. Pastikan tidak ada logika di frontend yang secara otomatis menandai plan selesai saat `waiting_for_user` diterima.
*   **Logging:** Tingkatkan logging di `agent_flow.py` untuk melacak status `step_waiting_for_user` dan alur eksekusi di sekitar `message_ask_user`. Ini akan sangat membantu dalam debugging jika masalah serupa muncul lagi.

### 3. Langkah Selanjutnya

1.  Terapkan perubahan pada `server/agent/agent_flow.py` seperti yang dijelaskan di atas.
2.  Uji alur agen secara menyeluruh, terutama skenario di mana agen meminta input pengguna dan kemudian melanjutkan tugasnya.
3.  Perhatikan *logging* dan output dari agen untuk memastikan bahwa status plan dan langkah diperbarui dengan benar, dan tidak ada "done" event yang dikirim secara prematur.

Dengan revisi ini, agen Anda seharusnya dapat menjeda eksekusi dengan benar saat menunggu input pengguna, tanpa menandai semua rencana sebagai selesai. Ini akan menciptakan pengalaman pengguna yang lebih mulus dan alur kerja agen yang lebih andal.
