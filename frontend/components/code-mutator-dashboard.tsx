"use client";

import { useState, useEffect } from "react";
import { DNAHelix } from "./dna-helix";
import {
  GitPullRequest,
  Bug,
  Sparkles,
  Radio,
  ExternalLink,
} from "lucide-react";

interface Signal {
  id: string;
  source: string;
  url: string;
  timestamp: string;
  type: "bug" | "feature" | "discussion";
  issue: string;
}

interface MutationEvent {
  id: string;
  title: string;
  commit: string;
  timestamp: string;
  type: "automated" | "bugfix" | "feature";
}

interface HoveredSignal {
  id: string;
  label: string;
  issue: string;
  type: "bug" | "feature" | "pr";
  position: { x: number; y: number };
  status: "generating" | "ready";
  prUrl?: string;
}

const mockSignals: Signal[] = [
  {
    id: "1",
    source: "GitHub Issues",
    url: "github.com/repo/issues/142",
    timestamp: "2 min ago",
    type: "bug",
    issue: "Memory leak in useEffect cleanup",
  },
  {
    id: "2",
    source: "Reddit r/programming",
    url: "reddit.com/r/programming/...",
    timestamp: "5 min ago",
    type: "discussion",
    issue: "Add dark mode toggle support",
  },
  {
    id: "3",
    source: "Twitter/X",
    url: "x.com/user/status/...",
    timestamp: "8 min ago",
    type: "feature",
    issue: "Implement batch export feature",
  },
  {
    id: "4",
    source: "Stack Overflow",
    url: "stackoverflow.com/q/...",
    timestamp: "12 min ago",
    type: "bug",
    issue: "Fix pagination offset calculation",
  },
  {
    id: "5",
    source: "Hacker News",
    url: "news.ycombinator.com/...",
    timestamp: "15 min ago",
    type: "discussion",
    issue: "Optimize database query performance",
  },
  {
    id: "6",
    source: "Discord #bugs",
    url: "discord.com/channels/...",
    timestamp: "18 min ago",
    type: "bug",
    issue: "Mobile responsive layout broken",
  },
];

const mockMutations: MutationEvent[] = [
  {
    id: "1",
    title: "Automated changes in automate",
    commit: "#25e08",
    timestamp: "03:08:50",
    type: "automated",
  },
  {
    id: "2",
    title: "Automated changes in changes",
    commit: "#47f86",
    timestamp: "22:08:45",
    type: "automated",
  },
  {
    id: "3",
    title: "Automated changes PRs",
    commit: "#27842",
    timestamp: "12:00:30",
    type: "automated",
  },
  {
    id: "4",
    title: "Bug Fixes implementation",
    commit: "#43088",
    timestamp: "12:08:05",
    type: "bugfix",
  },
  {
    id: "5",
    title: "Automated changes",
    commit: "#7329a",
    timestamp: "12:08:30",
    type: "automated",
  },
  {
    id: "6",
    title: "Feature Implementation",
    commit: "#25e08",
    timestamp: "12:50:13",
    type: "feature",
  },
  {
    id: "7",
    title: "Feature Implementation",
    commit: "#5a06c",
    timestamp: "12:58:27",
    type: "feature",
  },
  {
    id: "8",
    title: "Feature Implementation",
    commit: "#36022",
    timestamp: "12:58:17",
    type: "feature",
  },
  {
    id: "9",
    title: "Feature Implementation",
    commit: "#08325",
    timestamp: "13:58:12",
    type: "feature",
  },
];

export function CodeMutatorDashboard() {
  const [impactScore, setImpactScore] = useState(0);
  const [bugsCount] = useState(28);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [activeSignalIndex, setActiveSignalIndex] = useState<number | null>(
    null
  );
  const [hoveredSignal, setHoveredSignal] = useState<HoveredSignal | null>(
    null
  );
  const [isHoveringTooltip, setIsHoveringTooltip] = useState(false);
  const [persistedSignal, setPersistedSignal] = useState<HoveredSignal | null>(
    null
  );

  // The signal to display - persist it while hovering tooltip
  const displayedSignal = hoveredSignal || (isHoveringTooltip ? persistedSignal : null);

  // Simulate real-time updates
  useEffect(() => {
    const interval = setInterval(() => {
      setImpactScore((prev) =>
        Math.min(prev + Math.floor(Math.random() * 3), 100)
      );
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  // Pulse through signals
  useEffect(() => {
    const interval = setInterval(() => {
      setActiveSignalIndex((prev) => {
        if (prev === null) return 0;
        return (prev + 1) % mockSignals.length;
      });
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  // PR status for each signal (in real app, this would come from actual PR generation status)
  const signalStatus: Record<string, "generating" | "ready"> = {
    "1": "generating",
    "2": "generating",
    "3": "ready",
    "4": "generating",
    "5": "ready",
    "6": "ready",
  };

  // PR URLs for ready signals (in real app, this would come from the backend)
  const signalPrUrls: Record<string, string> = {
    "3": "https://github.com/your-repo/pull/142",
    "5": "https://github.com/your-repo/pull/143",
    "6": "https://github.com/your-repo/pull/144",
  };

  const helixSignals = mockSignals.slice(0, 4).map((signal, i) => ({
    id: signal.id,
    x: i % 2 === 0 ? 0.2 : 0.8,
    y: 0.15 + i * 0.22,
    label: signal.source,
    issue: signal.issue,
    status: signalStatus[signal.id] || "generating",
    prUrl: signalPrUrls[signal.id],
    type:
      signal.type === "bug"
        ? ("bug" as const)
        : signal.type === "feature"
          ? ("feature" as const)
          : ("pr" as const),
  }));

  const handleSignalHover = (
    signal: {
      id: string;
      label: string;
      issue: string;
      type: "bug" | "feature" | "pr";
      status?: "generating" | "ready";
      prUrl?: string;
    } | null,
    position: { x: number; y: number } | null
  ) => {
    if (signal && position) {
      const newSignal = {
        ...signal,
        position,
        status: signal.status || "generating",
        prUrl: signal.prUrl,
      };
      setHoveredSignal(newSignal);
      setPersistedSignal(newSignal); // Remember this for tooltip persistence
    } else {
      setHoveredSignal(null);
      // Don't clear persistedSignal here - let it persist for tooltip hover
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground font-mono flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-foreground flex items-center justify-center">
            <span className="text-background font-bold text-sm">D</span>
          </div>
          <h1 className="text-lg font-medium tracking-tight">
            Darwin
          </h1>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar */}
        <aside className="w-72 border-r border-border flex flex-col bg-sidebar">
          {/* Codebase Status */}
          <div className="p-4 border-b border-border">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-2 h-2 bg-foreground" />
              <span className="text-xs uppercase tracking-wider text-muted-foreground">
                Codebase Status
              </span>
            </div>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">
                  Impact Score
                </span>
                <span className="text-sm font-medium">{impactScore}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-muted-foreground">
                  Status: Bugs
                </span>
                <span className="text-sm font-medium">{bugsCount}</span>
              </div>
            </div>
          </div>

          {/* Active Signals */}
          <div className="p-4 flex-1 overflow-auto">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-2 h-2 bg-blue-500" />
              <span className="text-xs uppercase tracking-wider text-muted-foreground">
                Active Signals
              </span>
            </div>
            <p className="text-xs text-muted-foreground mb-3">
              Recent web scrapes
              <br />
              <span className="text-foreground/60">1/31/2026</span>
            </p>
            <div className="space-y-2">
              {mockSignals.map((signal, index) => (
                <div
                  key={signal.id}
                  className={`p-3 rounded border transition-all duration-300 ${activeSignalIndex === index
                    ? "border-foreground/40 bg-foreground/5"
                    : "border-border bg-card hover:border-foreground/20"
                    }`}
                >
                  <div className="flex items-start gap-2">
                    <Radio
                      className={`w-3 h-3 mt-1 ${activeSignalIndex === index ? "text-foreground animate-pulse" : "text-muted-foreground"}`}
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium truncate">
                        {signal.source}
                      </p>
                      <p className="text-xs text-muted-foreground truncate flex items-center gap-1">
                        <ExternalLink className="w-2.5 h-2.5" />
                        {signal.url}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* PR Activity */}
          <div className="p-4 border-t border-border">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-green-500" />
              <span className="text-xs uppercase tracking-wider text-muted-foreground">
                PR Activity
              </span>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <div className="flex -space-x-1">
                {[...Array(3)].map((_, i) => (
                  <div
                    key={i}
                    className="w-6 h-6 rounded-full border-2 border-sidebar bg-muted flex items-center justify-center"
                  >
                    <GitPullRequest className="w-3 h-3" />
                  </div>
                ))}
              </div>
              <span className="text-xs text-muted-foreground">
                3 PRs generating...
              </span>
            </div>
          </div>

          {/* Version */}
          <div className="p-4 border-t border-border flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-muted flex items-center justify-center">
              <span className="text-xs font-bold">D</span>
            </div>
            <span className="text-xs text-muted-foreground">Version 1.0</span>
          </div>
        </aside>

        {/* Main Canvas Area */}
        <main className="flex-1 relative overflow-hidden">
          {/* DNA Helix Visualization */}
          <div className="absolute inset-0">
            <DNAHelix
              signals={helixSignals}
              onSignalHover={handleSignalHover}
              isPaused={displayedSignal !== null}
            />
          </div>

          {/* Hover Annotation - Only shows when hovering a signal point */}
          {displayedSignal && (
            <div
              className="absolute z-10 transition-all duration-150"
              style={{
                left: displayedSignal.position.x,
                top: displayedSignal.position.y,
                transform: "translate(20px, -50%)",
              }}
              onMouseEnter={() => setIsHoveringTooltip(true)}
              onMouseLeave={() => {
                setIsHoveringTooltip(false);
                setPersistedSignal(null);
              }}
            >
              <div className="bg-card/95 backdrop-blur-sm border border-foreground/30 rounded-lg p-4 min-w-[240px] shadow-2xl">
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-8 h-8 rounded-full border border-foreground/40 flex items-center justify-center bg-background/80">
                    {displayedSignal.type === "bug" ? (
                      <Bug className="w-4 h-4" />
                    ) : displayedSignal.type === "feature" ? (
                      <Sparkles className="w-4 h-4" />
                    ) : (
                      <GitPullRequest className="w-4 h-4" />
                    )}
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground uppercase tracking-wider">
                      {displayedSignal.type === "bug"
                        ? "Bug Fix"
                        : displayedSignal.type === "feature"
                          ? "Feature Request"
                          : "Pull Request"}
                    </p>
                    <p className="text-sm font-medium">{displayedSignal.label}</p>
                  </div>
                </div>
                <div className="border-t border-border pt-3">
                  <p className="text-xs text-muted-foreground mb-1">Issue:</p>
                  <p className="text-sm text-foreground">
                    {displayedSignal.issue}
                  </p>
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${displayedSignal.status === "generating" ? "bg-yellow-500 animate-pulse" : "bg-green-500"}`} />
                    <span className={`text-xs ${displayedSignal.status === "generating" ? "text-yellow-400" : "text-green-400"}`}>
                      {displayedSignal.status === "generating" ? "Generating PR..." : "PR Ready for Review"}
                    </span>
                  </div>
                  {displayedSignal.status === "ready" && displayedSignal.prUrl && (
                    <a
                      href={displayedSignal.prUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-xs text-foreground hover:text-green-400 transition-colors"
                    >
                      <ExternalLink className="w-3 h-3" />
                      View PR
                    </a>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Bottom Action Bar */}
          <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-[90%] max-w-2xl">
            <div className="bg-card/80 backdrop-blur border border-border rounded-lg overflow-hidden">
              <input
                type="text"
                placeholder="Analyze for Signals and Generate PRs"
                className="w-full bg-transparent px-4 py-3 text-sm placeholder:text-muted-foreground focus:outline-none"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    setIsAnalyzing(true);
                    setTimeout(() => setIsAnalyzing(false), 3000);
                  }
                }}
              />
              {isAnalyzing && (
                <div className="h-0.5 bg-muted">
                  <div
                    className="h-full bg-foreground animate-pulse w-full"
                    style={{ animation: "pulse 1s ease-in-out infinite" }}
                  />
                </div>
              )}
            </div>
          </div>
        </main>

        {/* Right Sidebar - Mutation History */}
        <aside className="w-80 border-l border-border bg-sidebar overflow-auto">
          <div className="p-4">
            <div className="flex items-center gap-2 mb-6">
              <div className="w-2 h-2 bg-foreground" />
              <span className="text-xs uppercase tracking-wider text-muted-foreground">
                Mutation History
              </span>
            </div>
            <div className="space-y-1">
              {mockMutations.map((mutation, index) => (
                <div
                  key={mutation.id}
                  className="group flex items-start gap-3 py-3 border-b border-border/50 hover:bg-muted/30 transition-colors cursor-pointer"
                >
                  <div className="flex flex-col items-center">
                    <div
                      className={`w-2 h-2 rounded-full mt-1 ${mutation.type === "bugfix"
                        ? "bg-foreground"
                        : "bg-muted-foreground"
                        }`}
                    />
                    {index < mockMutations.length - 1 && (
                      <div className="w-px h-full bg-border mt-1" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">
                      {mutation.title}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Commit: {mutation.commit}
                    </p>
                  </div>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {mutation.timestamp}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
