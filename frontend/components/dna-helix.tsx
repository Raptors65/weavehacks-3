"use client";

import React from "react"

import { useEffect, useRef, useMemo, useState, useCallback } from "react";

interface Signal {
  id: string;
  x: number;
  y: number;
  label: string;
  issue: string;
  type: "bug" | "feature" | "pr";
  status?: "generating" | "ready";
  prUrl?: string;
}

interface SignalPoint {
  x: number;
  y: number;
  signal: Signal;
}

interface DNAHelixProps {
  signals?: Signal[];
  onSignalHover?: (signal: Signal | null, position: { x: number; y: number } | null) => void;
  isPaused?: boolean;
}

export function DNAHelix({ signals = [], onSignalHover, isPaused = false }: DNAHelixProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>(0);
  const timeRef = useRef<number>(0);
  const signalPointsRef = useRef<SignalPoint[]>([]);
  const [hoveredSignal, setHoveredSignal] = useState<string | null>(null);

  const helixConfig = useMemo(
    () => ({
      amplitude: 120,
      frequency: 0.008,
      verticalSpeed: 0.3,
      rotationSpeed: 0.015,
      particleCount: 80,
      connectionPairs: 20,
    }),
    []
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      let closestSignal: SignalPoint | null = null;
      let closestDistance = 30; // Detection radius

      for (const point of signalPointsRef.current) {
        const distance = Math.sqrt(
          Math.pow(mouseX - point.x, 2) + Math.pow(mouseY - point.y, 2)
        );
        if (distance < closestDistance) {
          closestDistance = distance;
          closestSignal = point;
        }
      }

      if (closestSignal) {
        setHoveredSignal(closestSignal.signal.id);
        onSignalHover?.(closestSignal.signal, { x: closestSignal.x, y: closestSignal.y });
      } else {
        setHoveredSignal(null);
        onSignalHover?.(null, null);
      }
    },
    [onSignalHover]
  );

  const handleMouseLeave = useCallback(() => {
    setHoveredSignal(null);
    onSignalHover?.(null, null);
  }, [onSignalHover]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resizeCanvas = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
    };

    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);

    const animate = () => {
      const rect = canvas.getBoundingClientRect();
      const width = rect.width;
      const height = rect.height;
      const centerX = width / 2;

      ctx.clearRect(0, 0, width, height);

      // Only increment time if not paused
      if (!isPaused) {
        timeRef.current += 1;
      }
      const time = timeRef.current;

      // Draw subtle grid background
      ctx.strokeStyle = "rgba(255, 255, 255, 0.03)";
      ctx.lineWidth = 1;
      const gridSize = 40;
      for (let x = 0; x < width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // Calculate helix points
      const strand1Points: { x: number; y: number; z: number; brightness: number }[] = [];
      const strand2Points: { x: number; y: number; z: number; brightness: number }[] = [];

      for (let i = 0; i < helixConfig.particleCount; i++) {
        const y = (i / helixConfig.particleCount) * (height + 200) - 100;
        const phase = y * helixConfig.frequency + time * helixConfig.rotationSpeed;

        const x1 = centerX + Math.cos(phase) * helixConfig.amplitude;
        const z1 = Math.sin(phase);
        const brightness1 = 0.3 + (z1 + 1) * 0.35;

        const x2 = centerX + Math.cos(phase + Math.PI) * helixConfig.amplitude;
        const z2 = Math.sin(phase + Math.PI);
        const brightness2 = 0.3 + (z2 + 1) * 0.35;

        strand1Points.push({ x: x1, y, z: z1, brightness: brightness1 });
        strand2Points.push({ x: x2, y, z: z2, brightness: brightness2 });
      }

      // Helper to draw strand particles
      const drawStrand = (points: typeof strand1Points, isBack: boolean) => {
        points.forEach((point) => {
          if (isBack && point.z >= 0) return;
          if (!isBack && point.z < 0) return;

          const size = 2 + point.brightness * 3;
          const glowSize = size * 4;

          const gradient = ctx.createRadialGradient(
            point.x,
            point.y,
            0,
            point.x,
            point.y,
            glowSize
          );
          gradient.addColorStop(0, `rgba(255, 255, 255, ${point.brightness * 0.8})`);
          gradient.addColorStop(0.3, `rgba(255, 255, 255, ${point.brightness * 0.3})`);
          gradient.addColorStop(1, "rgba(255, 255, 255, 0)");

          ctx.beginPath();
          ctx.arc(point.x, point.y, glowSize, 0, Math.PI * 2);
          ctx.fillStyle = gradient;
          ctx.fill();

          ctx.beginPath();
          ctx.arc(point.x, point.y, size, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255, 255, 255, ${point.brightness})`;
          ctx.fill();
        });
      };

      // Draw back strand particles first
      drawStrand(strand1Points, true);
      drawStrand(strand2Points, true);

      // Draw ALL connecting rungs with smooth z-based opacity (no hard threshold)
      // Sort by z so back rungs draw first
      const rungIndices: { i: number; avgZ: number }[] = [];
      for (let i = 0; i < helixConfig.particleCount; i += 4) {
        const p1 = strand1Points[i];
        const p2 = strand2Points[i];
        if (!p1 || !p2) continue;
        const avgZ = (p1.z + p2.z) / 2;
        rungIndices.push({ i, avgZ });
      }
      rungIndices.sort((a, b) => a.avgZ - b.avgZ);

      for (const { i, avgZ } of rungIndices) {
        const p1 = strand1Points[i];
        const p2 = strand2Points[i];
        if (!p1 || !p2) continue;

        // Smooth opacity based on z: ranges from ~0.1 (back) to ~0.4 (front)
        // Using (avgZ + 1) / 2 to normalize from [-1, 1] to [0, 1]
        const zNormalized = (avgZ + 1) / 2;
        const opacity = 0.1 + zNormalized * 0.3;
        const lineWidth = 1 + zNormalized * 0.5;
        const dotRadius = 1.5 + zNormalized * 0.5;

        ctx.strokeStyle = `rgba(255, 255, 255, ${opacity})`;
        ctx.lineWidth = lineWidth;
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();

        const dots = 6;
        for (let d = 1; d < dots; d++) {
          const t = d / dots;
          const dx = p1.x + (p2.x - p1.x) * t;
          const dy = p1.y + (p2.y - p1.y) * t;
          ctx.beginPath();
          ctx.arc(dx, dy, dotRadius, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255, 255, 255, ${opacity * 0.9})`;
          ctx.fill();
        }
      }

      // Draw front strand particles
      drawStrand(strand1Points, false);
      drawStrand(strand2Points, false);

      // Draw signal attachment points and store positions for hover detection
      const newSignalPoints: SignalPoint[] = [];

      signals.forEach((signal) => {
        const signalY = signal.y * height;
        const nearestIndex = Math.floor((signalY / height) * helixConfig.particleCount);
        const nearestPoint = strand1Points[Math.min(nearestIndex, strand1Points.length - 1)];
        if (!nearestPoint) return;

        // Store position for hover detection
        newSignalPoints.push({
          x: nearestPoint.x,
          y: nearestPoint.y,
          signal,
        });

        const isHovered = hoveredSignal === signal.id;
        const isReady = signal.status === "ready";
        
        // Color based on status: yellow for generating, green for ready
        const dotColor = isReady 
          ? { r: 34, g: 197, b: 94 }   // green-500
          : { r: 234, g: 179, b: 8 };  // yellow-500

        // Draw pulsing indicator at attachment point
        const basePulseSize = isHovered ? 14 : 10;
        const pulseSize = basePulseSize + Math.sin(time * 0.1) * 3;
        
        // Outer glow for hovered state
        if (isHovered) {
          const glowGradient = ctx.createRadialGradient(
            nearestPoint.x,
            nearestPoint.y,
            0,
            nearestPoint.x,
            nearestPoint.y,
            pulseSize * 2
          );
          glowGradient.addColorStop(0, `rgba(${dotColor.r}, ${dotColor.g}, ${dotColor.b}, 0.4)`);
          glowGradient.addColorStop(0.5, `rgba(${dotColor.r}, ${dotColor.g}, ${dotColor.b}, 0.1)`);
          glowGradient.addColorStop(1, `rgba(${dotColor.r}, ${dotColor.g}, ${dotColor.b}, 0)`);
          ctx.beginPath();
          ctx.arc(nearestPoint.x, nearestPoint.y, pulseSize * 2, 0, Math.PI * 2);
          ctx.fillStyle = glowGradient;
          ctx.fill();
        }

        // Pulsing ring
        ctx.beginPath();
        ctx.arc(nearestPoint.x, nearestPoint.y, pulseSize, 0, Math.PI * 2);
        ctx.strokeStyle = isHovered 
          ? `rgba(${dotColor.r}, ${dotColor.g}, ${dotColor.b}, 0.9)` 
          : `rgba(${dotColor.r}, ${dotColor.g}, ${dotColor.b}, 0.6)`;
        ctx.lineWidth = isHovered ? 3 : 2;
        ctx.stroke();

        // Inner dot
        ctx.beginPath();
        ctx.arc(nearestPoint.x, nearestPoint.y, isHovered ? 6 : 4, 0, Math.PI * 2);
        ctx.fillStyle = isHovered 
          ? `rgba(${dotColor.r}, ${dotColor.g}, ${dotColor.b}, 1)` 
          : `rgba(${dotColor.r}, ${dotColor.g}, ${dotColor.b}, 0.9)`;
        ctx.fill();
      });

      signalPointsRef.current = newSignalPoints;

      animationRef.current = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      window.removeEventListener("resize", resizeCanvas);
      cancelAnimationFrame(animationRef.current);
    };
  }, [helixConfig, signals, isPaused, hoveredSignal]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full cursor-crosshair"
      style={{ background: "transparent" }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    />
  );
}
