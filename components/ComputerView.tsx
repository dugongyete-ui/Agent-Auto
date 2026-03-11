import React, { useState, useRef, useEffect } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Image,
  Modal,
  SafeAreaView,
  StatusBar,
  Animated,
  Dimensions,
  ScrollView,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import type { AgentPlan } from "@/lib/chat";

const { width: SCREEN_WIDTH } = Dimensions.get("window");

interface BrowserState {
  url: string;
  title: string;
  content: string;
  screenshot?: string;
  isLoading: boolean;
}

interface ComputerViewProps {
  browserState: BrowserState | null;
  plan?: AgentPlan | null;
  onClose?: () => void;
}

function LiveIndicator() {
  const opacity = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.3, duration: 800, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 1, duration: 800, useNativeDriver: true }),
      ]),
    ).start();
  }, [opacity]);
  return (
    <View style={styles.liveRow}>
      <Animated.View style={[styles.liveDot, { opacity }]} />
      <Text style={styles.liveText}>Live</Text>
    </View>
  );
}

function ScanningAnimation() {
  const translateY = useRef(new Animated.Value(0)).current;
  const scanOpacity = useRef(new Animated.Value(0.7)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(translateY, { toValue: 80, duration: 1800, useNativeDriver: true }),
        Animated.timing(translateY, { toValue: 0, duration: 1800, useNativeDriver: true }),
      ]),
    ).start();
    Animated.loop(
      Animated.sequence([
        Animated.timing(scanOpacity, { toValue: 0.2, duration: 900, useNativeDriver: true }),
        Animated.timing(scanOpacity, { toValue: 0.7, duration: 900, useNativeDriver: true }),
      ]),
    ).start();
  }, [translateY, scanOpacity]);

  return (
    <View style={styles.scanContainer}>
      <View style={styles.scanGrid}>
        {[...Array(6)].map((_, i) => (
          <View key={i} style={styles.scanGridLine} />
        ))}
      </View>
      <Animated.View
        style={[styles.scanLine, { transform: [{ translateY }], opacity: scanOpacity }]}
      />
      <View style={styles.scanCornerTL} />
      <View style={styles.scanCornerTR} />
      <View style={styles.scanCornerBL} />
      <View style={styles.scanCornerBR} />
    </View>
  );
}

function EmptyBrowserState({ isLoading, url }: { isLoading: boolean; url: string }) {
  const dots = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!isLoading) return;
    Animated.loop(
      Animated.sequence([
        Animated.timing(dots, { toValue: 1, duration: 600, useNativeDriver: true }),
        Animated.timing(dots, { toValue: 0, duration: 600, useNativeDriver: true }),
      ]),
    ).start();
  }, [isLoading, dots]);

  if (isLoading) {
    return (
      <View style={styles.emptyStateContainer}>
        <ScanningAnimation />
        <View style={styles.emptyStateTextBox}>
          <View style={styles.loadingDots}>
            <Animated.View style={[styles.dot, { opacity: dots }]} />
            <Animated.View style={[styles.dot, { opacity: dots }]} />
            <Animated.View style={[styles.dot, { opacity: dots }]} />
          </View>
          <Text style={styles.emptyStateTitle}>Memuat halaman</Text>
          <Text style={styles.emptyStateUrl} numberOfLines={1}>
            {url || "Menghubungkan ke browser..."}
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.emptyStateContainer}>
      <View style={styles.emptyIconWrapper}>
        <Ionicons name="globe-outline" size={40} color="#2A2A35" />
      </View>
      <Text style={styles.emptyStateTitle}>Browser siap</Text>
      <Text style={styles.emptyStateSubtitle}>Screenshot akan muncul saat agen membuka halaman</Text>
    </View>
  );
}

function PlanBottomBar({ plan }: { plan: AgentPlan }) {
  const [expanded, setExpanded] = useState(false);
  const completedCount = plan.steps.filter((s) => s.status === "completed").length;
  const totalCount = plan.steps.length;
  const currentStep = plan.steps.find((s) => s.status === "running") ||
    plan.steps[plan.steps.length - 1];

  const progress = totalCount > 0 ? completedCount / totalCount : 0;
  const progressAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(progressAnim, {
      toValue: progress,
      duration: 400,
      useNativeDriver: false,
    }).start();
  }, [progress, progressAnim]);

  return (
    <View style={styles.planBar}>
      <View style={styles.progressBarTrack}>
        <Animated.View
          style={[
            styles.progressBarFill,
            {
              width: progressAnim.interpolate({
                inputRange: [0, 1],
                outputRange: ["0%", "100%"],
              }),
            },
          ]}
        />
      </View>

      <TouchableOpacity
        style={styles.planBarHeader}
        onPress={() => setExpanded(!expanded)}
        activeOpacity={0.7}
      >
        <View style={styles.planBarLeft}>
          <Ionicons
            name={completedCount === totalCount ? "checkmark-circle" : "layers-outline"}
            size={15}
            color={completedCount === totalCount ? "#30D158" : "#8E8E93"}
          />
          <Text style={styles.planBarTitle} numberOfLines={1}>
            {currentStep?.description || plan.title || "Menjalankan tugas"}
          </Text>
        </View>
        <View style={styles.planBarRight}>
          <Text style={styles.planBarCount}>
            {completedCount} / {totalCount}
          </Text>
          <Ionicons
            name={expanded ? "chevron-down" : "chevron-up"}
            size={13}
            color="#636366"
          />
        </View>
      </TouchableOpacity>

      {expanded && (
        <View style={styles.planBarSteps}>
          {plan.steps.map((step, i) => (
            <View key={step.id || i} style={styles.planBarStep}>
              <Ionicons
                name={
                  step.status === "completed"
                    ? "checkmark-circle"
                    : step.status === "running"
                    ? "radio-button-on"
                    : step.status === "failed"
                    ? "close-circle"
                    : "radio-button-off"
                }
                size={13}
                color={
                  step.status === "completed"
                    ? "#30D158"
                    : step.status === "running"
                    ? "#6C5CE7"
                    : step.status === "failed"
                    ? "#FF453A"
                    : "#3A3A3F"
                }
              />
              <Text
                style={[
                  styles.planBarStepText,
                  step.status === "completed" && styles.planBarStepDone,
                  step.status === "running" && styles.planBarStepRunning,
                ]}
                numberOfLines={1}
              >
                {step.description}
              </Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

function ToolBadge({ tool }: { tool: "browser" | "e2b" | "file" | "search" }) {
  const config = {
    browser: { icon: "globe-outline" as const, label: "Browser", color: "#6C5CE7" },
    e2b: { icon: "terminal-outline" as const, label: "E2B Sandbox", color: "#FF9F0A" },
    file: { icon: "document-outline" as const, label: "File", color: "#30D158" },
    search: { icon: "search-outline" as const, label: "Search", color: "#0A84FF" },
  };
  const c = config[tool];
  return (
    <View style={[styles.toolBadge, { borderColor: c.color + "40" }]}>
      <Ionicons name={c.icon} size={10} color={c.color} />
      <Text style={[styles.toolBadgeText, { color: c.color }]}>{c.label}</Text>
    </View>
  );
}

function FullScreenBrowser({
  browserState,
  plan,
  onClose,
}: {
  browserState: BrowserState;
  plan?: AgentPlan | null;
  onClose?: () => void;
}) {
  return (
    <View style={styles.fullContainer}>
      <StatusBar barStyle="light-content" backgroundColor="#000000" />

      <SafeAreaView style={styles.fullHeader}>
        <View style={styles.fullHeaderInner}>
          <TouchableOpacity onPress={onClose} style={styles.headerCloseBtn} activeOpacity={0.7}>
            <Ionicons name="close" size={20} color="#FFFFFF" />
          </TouchableOpacity>
          <View style={styles.fullHeaderCenter}>
            <Text style={styles.fullHeaderTitle}>Komputer Dzeck</Text>
            <ToolBadge tool="browser" />
          </View>
          <View style={styles.headerCloseBtn}>
            {browserState.isLoading ? (
              <Ionicons name="sync" size={16} color="#6C5CE7" />
            ) : (
              <Ionicons name="scan-outline" size={18} color="#8E8E93" />
            )}
          </View>
        </View>
      </SafeAreaView>

      <View style={styles.browserViewport}>
        <View style={styles.browserUrlBar}>
          <Ionicons name="lock-closed" size={10} color="#34C759" />
          <Text style={styles.browserUrlText} numberOfLines={1}>
            {browserState.url || "about:blank"}
          </Text>
          {browserState.isLoading && (
            <View style={styles.loadingIndicator}>
              <Ionicons name="sync" size={11} color="#6C5CE7" />
            </View>
          )}
        </View>

        <View style={styles.browserContent}>
          {browserState.screenshot ? (
            <Image
              source={{ uri: browserState.screenshot }}
              style={styles.browserScreenshot}
              resizeMode="cover"
            />
          ) : browserState.content ? (
            <ScrollView style={styles.browserTextScroll}>
              <Text style={styles.browserTextContent}>{browserState.content}</Text>
            </ScrollView>
          ) : (
            <EmptyBrowserState isLoading={browserState.isLoading} url={browserState.url} />
          )}

          <View style={styles.takeControlOverlay}>
            <TouchableOpacity style={styles.takeControlBtn} activeOpacity={0.75}>
              <Ionicons name="camera-outline" size={15} color="#FFFFFF" />
              <Text style={styles.takeControlText}>Ambil kendali</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.navBar}>
          <TouchableOpacity style={styles.navBtn} activeOpacity={0.7}>
            <Ionicons name="play-skip-back" size={18} color="#8E8E93" />
          </TouchableOpacity>
          <LiveIndicator />
          <TouchableOpacity style={styles.navBtn} activeOpacity={0.7}>
            <Ionicons name="play-skip-forward" size={18} color="#8E8E93" />
          </TouchableOpacity>
        </View>
      </View>

      {plan && plan.steps.length > 0 && (
        <PlanBottomBar plan={plan} />
      )}
    </View>
  );
}

export function ComputerView({ browserState, plan, onClose }: ComputerViewProps) {
  const [fullScreen, setFullScreen] = useState(false);

  if (!browserState) return null;

  return (
    <>
      <TouchableOpacity
        style={styles.compactCard}
        onPress={() => setFullScreen(true)}
        activeOpacity={0.8}
      >
        <View style={styles.compactHeader}>
          <View style={styles.compactHeaderLeft}>
            <Ionicons name="desktop-outline" size={14} color="#6C5CE7" />
            <Text style={styles.compactTitle}>Komputer Dzeck</Text>
            <ToolBadge tool="browser" />
          </View>
          <View style={styles.compactHeaderRight}>
            {browserState.isLoading ? (
              <Ionicons name="sync" size={12} color="#6C5CE7" />
            ) : (
              <View style={styles.compactLiveDot} />
            )}
            <Ionicons name="expand-outline" size={13} color="#636366" />
          </View>
        </View>

        <View style={styles.compactBody}>
          {browserState.screenshot ? (
            <Image
              source={{ uri: browserState.screenshot }}
              style={styles.compactScreenshot}
              resizeMode="cover"
            />
          ) : (
            <View style={styles.compactEmptyState}>
              {browserState.isLoading ? (
                <>
                  <ScanningAnimation />
                  <Text style={styles.compactLoadingText}>Memuat halaman...</Text>
                </>
              ) : (
                <>
                  <Ionicons name="globe-outline" size={22} color="#2C2C38" />
                  <Text style={styles.compactEmptyText}>Tap untuk membuka browser</Text>
                </>
              )}
            </View>
          )}
        </View>

        <View style={styles.compactFooter}>
          <Ionicons name="lock-closed" size={9} color="#34C759" />
          <Text style={styles.compactUrl} numberOfLines={1}>
            {browserState.url || "about:blank"}
          </Text>
          {browserState.isLoading && (
            <Text style={styles.compactLoadingBadge}>loading</Text>
          )}
        </View>
      </TouchableOpacity>

      <Modal
        visible={fullScreen}
        animationType="slide"
        statusBarTranslucent
        onRequestClose={() => setFullScreen(false)}
      >
        <FullScreenBrowser
          browserState={browserState}
          plan={plan}
          onClose={() => setFullScreen(false)}
        />
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  // ─── Compact inline card ───────────────────────────────
  compactCard: {
    backgroundColor: "#0E0E13",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#1E1E28",
    overflow: "hidden",
    marginHorizontal: 16,
    marginVertical: 6,
  },
  compactHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 12,
    paddingVertical: 9,
    backgroundColor: "#13131A",
    borderBottomWidth: 1,
    borderBottomColor: "#1E1E28",
  },
  compactHeaderLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    flex: 1,
  },
  compactTitle: {
    fontFamily: "Inter_500Medium",
    fontSize: 12,
    color: "#E8E8ED",
  },
  compactHeaderRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  compactLiveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: "#30D158",
  },
  compactBody: {
    height: 130,
    backgroundColor: "#080810",
    overflow: "hidden",
  },
  compactScreenshot: {
    width: "100%",
    height: "100%",
  },
  compactEmptyState: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  compactLoadingText: {
    fontFamily: "Inter_400Regular",
    fontSize: 11,
    color: "#6C5CE7",
  },
  compactEmptyText: {
    fontFamily: "Inter_400Regular",
    fontSize: 11,
    color: "#3A3A45",
  },
  compactFooter: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 6,
    backgroundColor: "#0B0B10",
  },
  compactUrl: {
    flex: 1,
    fontFamily: "monospace",
    fontSize: 10,
    color: "#4A4A55",
  },
  compactLoadingBadge: {
    fontFamily: "Inter_400Regular",
    fontSize: 9,
    color: "#6C5CE7",
    backgroundColor: "rgba(108,92,231,0.15)",
    paddingHorizontal: 5,
    paddingVertical: 2,
    borderRadius: 4,
  },

  // ─── Full screen modal ────────────────────────────────
  fullContainer: {
    flex: 1,
    backgroundColor: "#000000",
  },
  fullHeader: {
    backgroundColor: "#000000",
  },
  fullHeaderInner: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  fullHeaderCenter: {
    flex: 1,
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "center",
    gap: 8,
  },
  headerCloseBtn: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: "rgba(255,255,255,0.06)",
    alignItems: "center",
    justifyContent: "center",
  },
  fullHeaderTitle: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 15,
    color: "#FFFFFF",
    letterSpacing: -0.3,
  },
  browserViewport: {
    flex: 1,
    backgroundColor: "#0E0E14",
    marginHorizontal: 12,
    borderRadius: 14,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#1E1E2A",
    marginBottom: 8,
  },
  browserUrlBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#0B0B10",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: "#1A1A22",
  },
  browserUrlText: {
    flex: 1,
    fontFamily: "monospace",
    fontSize: 11,
    color: "rgba(255,255,255,0.4)",
  },
  loadingIndicator: {
    opacity: 0.8,
  },
  browserContent: {
    flex: 1,
    position: "relative",
  },
  browserScreenshot: {
    width: "100%",
    height: "100%",
  },
  browserTextScroll: {
    flex: 1,
    padding: 12,
  },
  browserTextContent: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: "#C0C0C8",
    lineHeight: 18,
  },
  // "Ambil kendali" overlay
  takeControlOverlay: {
    position: "absolute",
    bottom: 16,
    left: 0,
    right: 0,
    alignItems: "center",
  },
  takeControlBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "rgba(0,0,0,0.72)",
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 9,
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.1)",
  },
  takeControlText: {
    fontFamily: "Inter_500Medium",
    fontSize: 13,
    color: "#FFFFFF",
  },
  // Bottom nav bar
  navBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingVertical: 10,
    backgroundColor: "#0B0B10",
    borderTopWidth: 1,
    borderTopColor: "#1A1A22",
  },
  navBtn: {
    padding: 4,
  },
  liveRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  liveDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#30D158",
  },
  liveText: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 13,
    color: "#FFFFFF",
  },

  // ─── Empty state ──────────────────────────────────────
  emptyStateContainer: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 16,
    padding: 24,
  },
  emptyIconWrapper: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: "#111118",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "#1E1E28",
  },
  emptyStateTitle: {
    fontFamily: "Inter_500Medium",
    fontSize: 14,
    color: "#6C6C78",
  },
  emptyStateSubtitle: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: "#3A3A45",
    textAlign: "center",
    lineHeight: 18,
  },
  emptyStateTextBox: {
    alignItems: "center",
    gap: 4,
  },
  emptyStateUrl: {
    fontFamily: "monospace",
    fontSize: 10,
    color: "#4A4A58",
    maxWidth: 200,
    textAlign: "center",
  },

  // ─── Loading dots ─────────────────────────────────────
  loadingDots: {
    flexDirection: "row",
    gap: 4,
    marginBottom: 4,
  },
  dot: {
    width: 5,
    height: 5,
    borderRadius: 2.5,
    backgroundColor: "#6C5CE7",
  },

  // ─── Scan animation ───────────────────────────────────
  scanContainer: {
    width: 100,
    height: 100,
    borderRadius: 8,
    backgroundColor: "#0A0A14",
    overflow: "hidden",
    position: "relative",
    borderWidth: 1,
    borderColor: "#6C5CE730",
  },
  scanGrid: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    opacity: 0.08,
  },
  scanGridLine: {
    height: 1,
    backgroundColor: "#6C5CE7",
    marginVertical: 13,
  },
  scanLine: {
    position: "absolute",
    left: 0,
    right: 0,
    height: 2,
    backgroundColor: "#6C5CE7",
    shadowColor: "#6C5CE7",
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.8,
    shadowRadius: 4,
    ...(Platform.OS === "android" ? { elevation: 4 } : {}),
  },
  scanCornerTL: {
    position: "absolute",
    top: 4,
    left: 4,
    width: 12,
    height: 12,
    borderTopWidth: 2,
    borderLeftWidth: 2,
    borderColor: "#6C5CE7",
  },
  scanCornerTR: {
    position: "absolute",
    top: 4,
    right: 4,
    width: 12,
    height: 12,
    borderTopWidth: 2,
    borderRightWidth: 2,
    borderColor: "#6C5CE7",
  },
  scanCornerBL: {
    position: "absolute",
    bottom: 4,
    left: 4,
    width: 12,
    height: 12,
    borderBottomWidth: 2,
    borderLeftWidth: 2,
    borderColor: "#6C5CE7",
  },
  scanCornerBR: {
    position: "absolute",
    bottom: 4,
    right: 4,
    width: 12,
    height: 12,
    borderBottomWidth: 2,
    borderRightWidth: 2,
    borderColor: "#6C5CE7",
  },

  // ─── Plan bottom bar ──────────────────────────────────
  planBar: {
    backgroundColor: "#0E0E13",
    borderTopWidth: 1,
    borderTopColor: "#1E1E28",
    paddingBottom: 8,
  },
  progressBarTrack: {
    height: 2,
    backgroundColor: "#1A1A22",
  },
  progressBarFill: {
    height: 2,
    backgroundColor: "#6C5CE7",
  },
  planBarHeader: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 10,
    gap: 8,
  },
  planBarLeft: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  planBarTitle: {
    flex: 1,
    fontFamily: "Inter_500Medium",
    fontSize: 13,
    color: "#E8E8ED",
    letterSpacing: -0.2,
  },
  planBarRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  planBarCount: {
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: "#636366",
  },
  planBarSteps: {
    paddingHorizontal: 16,
    paddingBottom: 6,
    gap: 6,
  },
  planBarStep: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  planBarStepText: {
    flex: 1,
    fontFamily: "Inter_400Regular",
    fontSize: 12,
    color: "#636366",
    lineHeight: 17,
  },
  planBarStepDone: {
    color: "#3A3A45",
  },
  planBarStepRunning: {
    color: "#E8E8ED",
  },

  // ─── Tool badge ───────────────────────────────────────
  toolBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    borderWidth: 1,
    backgroundColor: "transparent",
  },
  toolBadgeText: {
    fontFamily: "Inter_500Medium",
    fontSize: 9,
    letterSpacing: 0.2,
  },
});
