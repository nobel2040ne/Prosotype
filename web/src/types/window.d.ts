import type {CaptionEvent} from "@/lib/caption-store";

declare global {
  interface Window {
    __cwiStudio?: {
      dispatch: (event: CaptionEvent, eventId?: number) => void;
      report: () => {
        connection: string;
        words: number;
        visible: number;
        activeMotions: number;
        pendingReveals: number;
        motionStarts: number;
        motionPaintStarts: number;
        motionsWithoutPaint: number;
        abortedUnpaintedMotions: number;
        presentationBacklogMs: number;
        maxPresentationBacklogMs: number;
        adaptiveMotionStarts: number;
        minimumMotionDurationMs: number;
        motionEligibleWords: number;
        freshWordsWithoutMotion: number;
        directionKnown: boolean;
      };
    };
  }
}

export {};
