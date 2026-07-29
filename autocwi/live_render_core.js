(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.CWIRenderCore = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const STATUS_RANK = Object.freeze({
    unknown: 0,
    provisional: 1,
    stable: 2,
    corrected: 3
  });
  const STAGE_RANK = Object.freeze({
    hypothesis: 0,
    cue: 1,
    commit: 2,
    word: 3,
    verification: 4
  });

  function finiteNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function speakerStatus(word) {
    if (STATUS_RANK[word && word.speaker_status] !== undefined) {
      return word.speaker_status;
    }
    return word && word.speaker_known === false ? "unknown" : "stable";
  }

  function wordKey(word) {
    if (word && word.word_id) return String(word.word_id);
    const utterance = finiteNumber(word && word.utterance, 0);
    const onset = finiteNumber(word && word.t, finiteNumber(word && word.start, 0));
    return "legacy:" + utterance + ":" + Math.round(onset * 20);
  }

  function eventStage(word) {
    if (word && word._render_stage) return word._render_stage;
    if (word && word.verified) return "verification";
    if (word && word.type === "commit") return "commit";
    if (word && word.type === "cue") return "cue";
    if (word && word.type === "hypothesis") return "hypothesis";
    return word && word.final ? "word" : "hypothesis";
  }

  function sourceRank(word) {
    if (!word || !word.src) return 2;
    return word.src === "accurate" ? 2 : 1;
  }

  function eventMeta(word) {
    const stage = eventStage(word);
    const stageRank = STAGE_RANK[stage] === undefined ? 0 : STAGE_RANK[stage];
    return {
      textRevision: finiteNumber(word && word.text_revision_id, 0),
      timingRevision: finiteNumber(word && word.timing_revision_id, 0),
      speakerRevision: finiteNumber(word && word.speaker_revision_id, 0),
      stageRank: stageRank,
      finalRank: word && word.verified ? 2 : (word && word.final ? 1 : 0),
      statusRank: STATUS_RANK[speakerStatus(word)],
      sourceRank: sourceRank(word),
      sseId: finiteNumber(word && word._sse_id, 0)
    };
  }

  function compareRevision(incoming, current, channel) {
    const a = eventMeta(incoming);
    const b = eventMeta(current);
    // Draft and accurate recognizers own independent counters. Their numeric
    // revisions are not comparable; source authority is. Once an accurate
    // slot exists, a later draft snapshot cannot take ownership back.
    if (a.sourceRank !== b.sourceRank) return Math.sign(a.sourceRank - b.sourceRank);
    const field = channel + "Revision";
    if (a[field] !== b[field]) return Math.sign(a[field] - b[field]);
    if (a.finalRank !== b.finalRank) return Math.sign(a.finalRank - b.finalRank);
    if (a.stageRank !== b.stageRank) return Math.sign(a.stageRank - b.stageRank);
    return Math.sign(a.sseId - b.sseId);
  }

  function speakerDecision(incoming, current) {
    const a = eventMeta(incoming);
    const b = eventMeta(current);
    const incomingStatus = speakerStatus(incoming);
    const currentStatus = speakerStatus(current);

    // A delayed tentative observation must never visually roll a stable word
    // back. A changed stable identity also needs an explicit corrected state.
    if (b.statusRank >= STATUS_RANK.stable &&
        a.statusRank < STATUS_RANK.stable) {
      return {apply: false, stale: true, reason: "stable speaker cannot downgrade"};
    }
    if (b.statusRank >= STATUS_RANK.stable &&
        incoming && current && incoming.speaker !== current.speaker &&
        incomingStatus !== "corrected") {
      return {apply: false, stale: true, reason: "speaker change lacks correction"};
    }
    if (a.speakerRevision < b.speakerRevision) {
      return {apply: false, stale: true, reason: "older speaker revision"};
    }
    if (a.speakerRevision > b.speakerRevision) {
      return {apply: true, stale: false, reason: null};
    }
    if (a.statusRank !== b.statusRank) {
      return {
        apply: a.statusRank > b.statusRank,
        stale: a.statusRank < b.statusRank,
        reason: a.statusRank < b.statusRank ? "older speaker state" : null
      };
    }
    const newer = compareRevision(incoming, current, "speaker") > 0;
    return {
      apply: newer,
      stale: !newer && a.sseId < b.sseId,
      reason: !newer && a.sseId < b.sseId ? "older speaker event" : null
    };
  }

  function copyFields(target, source, fields) {
    fields.forEach(field => {
      if (Object.prototype.hasOwnProperty.call(source, field)) {
        target[field] = source[field];
      }
    });
  }

  const TEXT_FIELDS = ["text", "text_revision_id"];
  const TIMING_FIELDS = ["t", "start", "end", "timing_revision_id"];
  const SPEAKER_FIELDS = [
    "speaker", "speaker_known", "speaker_status", "speaker_confidence",
    "speaker_change_probability", "speaker_revision_id", "speaker_reason",
    "overlap"
  ];

  function mergeWordUpdate(current, incoming) {
    if (!current) {
      return {
        value: Object.assign({}, incoming),
        changed: true,
        stale: false,
        changes: {text: true, timing: true, speaker: true, final: true},
        reason: null
      };
    }
    if (wordKey(current) !== wordKey(incoming)) {
      throw new Error("cannot merge different word identities");
    }

    const out = Object.assign({}, current);
    const changes = {text: false, timing: false, speaker: false, final: false};
    const reasons = [];
    let stale = false;

    const textCmp = compareRevision(incoming, current, "text");
    const currentFinal = eventMeta(current).finalRank;
    const incomingFinal = eventMeta(incoming).finalRank;
    const textAllowed = !(currentFinal > incomingFinal);
    if (textAllowed && textCmp > 0) {
      if (incoming.text !== current.text) changes.text = true;
      copyFields(out, incoming, TEXT_FIELDS);
    } else if (incoming.text !== current.text && (!textAllowed || textCmp < 0)) {
      stale = true;
      reasons.push(!textAllowed ? "final text cannot downgrade" : "older text revision");
    }

    const timingCmp = compareRevision(incoming, current, "timing");
    if (textAllowed && timingCmp > 0) {
      changes.timing = TIMING_FIELDS.some(field =>
        incoming[field] !== undefined && incoming[field] !== current[field]);
      copyFields(out, incoming, TIMING_FIELDS);
    } else if (timingCmp < 0) {
      stale = true;
      reasons.push("older timing revision");
    }

    const speaker = speakerDecision(incoming, current);
    if (speaker.apply) {
      changes.speaker = SPEAKER_FIELDS.some(field =>
        incoming[field] !== undefined && incoming[field] !== current[field]);
      copyFields(out, incoming, SPEAKER_FIELDS);
    } else if (speaker.stale) {
      stale = true;
      if (speaker.reason) reasons.push(speaker.reason);
    }

    // Non-revision fields follow the most authoritative event only. This keeps
    // reconnect replay from replacing verified prosody/confidence with an old
    // hypothesis while still allowing a verification to fill those fields.
    if (incomingFinal > currentFinal ||
        (incomingFinal === currentFinal &&
         eventMeta(incoming).stageRank >= eventMeta(current).stageRank &&
         eventMeta(incoming).sseId >= eventMeta(current).sseId)) {
      const protectedFields = new Set(
        [...TEXT_FIELDS, ...TIMING_FIELDS, ...SPEAKER_FIELDS]
      );
      Object.keys(incoming).forEach(field => {
        if (!protectedFields.has(field)) out[field] = incoming[field];
      });
    }

    const wasFinal = Boolean(current.final);
    const wasVerified = Boolean(current.verified);
    out.final = wasFinal || Boolean(incoming.final);
    out.verified = wasVerified || Boolean(incoming.verified);
    out.provisional = out.verified ? false :
      (Boolean(current.provisional) || Boolean(incoming.provisional));
    changes.final = out.final !== wasFinal || out.verified !== wasVerified;
    if (out.verified) out._render_stage = "verification";
    else if (out.final) out._render_stage = "word";
    else if (eventMeta(incoming).stageRank >= eventMeta(current).stageRank) {
      out._render_stage = eventStage(incoming);
    }
    out._sse_id = Math.max(
      finiteNumber(current._sse_id, 0), finiteNumber(incoming._sse_id, 0)
    );

    const changed = changes.text || changes.timing || changes.speaker ||
      changes.final || eventStage(out) !== eventStage(current);
    return {
      value: out,
      changed: changed,
      stale: stale,
      changes: changes,
      reason: reasons.length ? Array.from(new Set(reasons)).join("; ") : null
    };
  }

  function createFrameReducer(limit) {
    const maximum = Math.max(1, finiteNumber(limit, 512));
    const pending = new Map();
    let sequence = 0;
    const stats = {
      received: 0,
      coalesced: 0,
      discarded: 0,
      stale: 0,
      evicted: 0,
      maxDepth: 0
    };
    return {
      enqueue(update) {
        stats.received += 1;
        const key = wordKey(update);
        const prior = pending.get(key);
        if (prior) {
          const merged = mergeWordUpdate(prior.value, update);
          stats.coalesced += 1;
          if (merged.stale) stats.stale += 1;
          if (!merged.changed) stats.discarded += 1;
          prior.value = merged.value;
          prior.merge = merged;
        } else {
          pending.set(key, {value: Object.assign({}, update), order: sequence++});
        }
        while (pending.size > maximum) {
          pending.delete(pending.keys().next().value);
          stats.evicted += 1;
        }
        stats.maxDepth = Math.max(stats.maxDepth, pending.size);
        return pending.get(key);
      },
      drain() {
        const values = Array.from(pending.values())
          .sort((a, b) => {
            const at = finiteNumber(a.value.t, finiteNumber(a.value.start, 0));
            const bt = finiteNumber(b.value.t, finiteNumber(b.value.start, 0));
            return at - bt || a.order - b.order;
          })
          .map(entry => entry.value);
        pending.clear();
        return values;
      },
      reset() {
        pending.clear();
      },
      get size() {
        return pending.size;
      },
      has(key) {
        return pending.has(String(key));
      },
      stats: stats
    };
  }

  function reduceTentativeTail(incoming, mode, settledKeys, capacity) {
    if (mode === "stable" || mode === "sentence") return [];
    const settled = settledKeys || new Set();
    let words = (incoming || []).filter(word => !settled.has(wordKey(word)));
    if (mode === "fast") {
      words = words.filter(word => word.src !== "draft");
    } else {
      const accurate = words.filter(word => word.src !== "draft");
      words = words.filter(word => word.src !== "draft" || !accurate.some(other =>
        Math.abs(finiteNumber(other.t, 0) - finiteNumber(word.t, 0)) < 0.22
      ));
    }
    words.sort((a, b) =>
      finiteNumber(a.t, finiteNumber(a.start, 0)) -
      finiteNumber(b.t, finiteNumber(b.start, 0)) ||
      sourceRank(b) - sourceRank(a)
    );
    const limit = capacity === undefined ? words.length : Math.max(0, capacity);
    return words.slice(0, limit);
  }

  function createMediaClock(options) {
    const smoothing = finiteNumber(options && options.smoothing, 0.18);
    const resetThreshold = finiteNumber(options && options.resetThreshold, 0.75);
    let anchorSource = null;
    let anchorPerformance = null;
    return {
      observe(sourceSeconds, performanceMs) {
        const source = finiteNumber(sourceSeconds, null);
        const perf = finiteNumber(performanceMs, null);
        if (source === null || perf === null) return;
        if (anchorSource === null) {
          anchorSource = source;
          anchorPerformance = perf;
          return;
        }
        const predicted = anchorSource + (perf - anchorPerformance) / 1000;
        const error = source - predicted;
        if (Math.abs(error) > resetThreshold) {
          anchorSource = source;
          anchorPerformance = perf;
        } else {
          anchorSource = predicted + error * smoothing;
          anchorPerformance = perf;
        }
      },
      sourceAt(performanceMs) {
        if (anchorSource === null) return null;
        return anchorSource +
          (finiteNumber(performanceMs, anchorPerformance) - anchorPerformance) / 1000;
      },
      performanceAt(sourceSeconds) {
        if (anchorSource === null) return null;
        return anchorPerformance +
          (finiteNumber(sourceSeconds, anchorSource) - anchorSource) * 1000;
      },
      reset() {
        anchorSource = null;
        anchorPerformance = null;
      },
      get anchored() {
        return anchorSource !== null;
      }
    };
  }

  function syncEnvelope(elapsed, timing) {
    const attack = Math.max(1e-6, finiteNumber(timing && timing.rise_s, 0.09));
    const hold = Math.max(0, finiteNumber(timing && timing.peak_s, 0.08));
    const release = Math.max(1e-6, finiteNumber(timing && timing.fall_s, 0.18));
    if (elapsed <= 0) return 0;
    if (elapsed < attack) {
      const x = Math.min(1, Math.max(0, elapsed / attack));
      return x * x * (3 - 2 * x);
    }
    if (elapsed < attack + hold) return 1;
    if (elapsed < attack + hold + release) {
      const x = (elapsed - attack - hold) / release;
      const smooth = x * x * (3 - 2 * x);
      return 1 - smooth;
    }
    return 0;
  }

  function motionDuration(timing) {
    return Math.max(0, finiteNumber(timing && timing.rise_s, 0.09)) +
      Math.max(0, finiteNumber(timing && timing.peak_s, 0.08)) +
      Math.max(0, finiteNumber(timing && timing.fall_s, 0.18));
  }

  function characterEntryDelays(text, staggerSeconds) {
    const step = Math.max(0, finiteNumber(staggerSeconds, 0.018));
    return Array.from(String(text || "")).map((_, index) => index * step);
  }

  function planMotion(word, clock, performanceMs, timing, options) {
    const now = finiteNumber(performanceMs, 0);
    const onset = finiteNumber(word && word.t, finiteNumber(word && word.start, 0));
    const duration = motionDuration(timing);
    const reduced = Boolean(options && options.reducedMotion);
    const replay = Boolean(options && options.replay);
    let onsetPerformance = clock && clock.performanceAt(onset);
    if (onsetPerformance === null || onsetPerformance === undefined) {
      onsetPerformance = now;
    }
    const elapsed = Math.max(0, (now - onsetPerformance) / 1000);
    if (reduced) {
      return {
        state: "reduced", onsetPerformance, elapsed, duration, trigger: "reduced"
      };
    }
    if (replay) {
      return {
        state: "settled", onsetPerformance, elapsed, duration, trigger: "replay"
      };
    }
    if (options && options.displayOnCreate) {
      return {
        state: "active", onsetPerformance: now, elapsed: 0, duration,
        trigger: "display"
      };
    }
    if (now < onsetPerformance) {
      return {
        state: "scheduled", onsetPerformance, elapsed: 0, duration,
        trigger: "source"
      };
    }
    if (elapsed >= duration) {
      return {
        state: "settled", onsetPerformance, elapsed, duration, trigger: "source"
      };
    }
    return {
      state: "active", onsetPerformance, elapsed, duration, trigger: "source"
    };
  }

  function nextRevealDeadline(currentDeadline, now, gap, catchupGap) {
    const present = finiteNumber(now, 0);
    const current = finiteNumber(currentDeadline, 0);
    const base = current > 0 ? current : present;
    return Math.max(
      base + Math.max(0, finiteNumber(gap, 0)),
      present + Math.max(0, finiteNumber(catchupGap, 0))
    );
  }

  return Object.freeze({
    STATUS_RANK,
    STAGE_RANK,
    speakerStatus,
    wordKey,
    eventStage,
    eventMeta,
    compareRevision,
    mergeWordUpdate,
    createFrameReducer,
    reduceTentativeTail,
    createMediaClock,
    syncEnvelope,
    motionDuration,
    characterEntryDelays,
    planMotion,
    nextRevealDeadline,
  });
}));
