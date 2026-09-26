// Source: openclaw/openclaw commit eb4f3d792f416df4f24f1dd4037b14d79891b6ba.
// Import specifiers point at the chunk names of the openclaw@2026.7.1-2 build.
import { t as createLazyImportLoader } from "./lazy-promise-10KxeiYV.js";
import { i as isCronSessionKey } from "./session-key-utils-A-JGvyXu.js";
import { a as logWarn } from "./logger-D7QYAmug.js";
import { o as normalizeDeliveryContext } from "./delivery-context.shared-3o3tBaCD.js";
import { t as INTERNAL_MESSAGE_CHANNEL } from "./message-channel-constants-BXOA4cxJ.js";
import "./message-channel-CB9y2CYk.js";
import { n as SILENT_REPLY_TOKEN } from "./tokens-DKI4eGAu.js";
import { E as hasSubagentRunEnded } from "./subagent-registry-state-CP7kKu69.js";
import { s as getSubagentDepthFromSessionStore } from "./subagent-capabilities-tqhxY1k6.js";
import "./delivery-context-v0-gU4Pa.js";
import { i as loadRequesterSessionEntry, n as deliverSubagentAnnouncement, t as resolveAnnounceOrigin } from "./subagent-announce-origin-DPSebzOW.js";
import { o as dedupeLatestChildCompletionRows, r as buildChildCompletionFindings, s as filterCurrentDirectChildCompletionRows } from "./subagent-session-cleanup-BEPym0Sy.js";
import { n as buildAnnounceIdempotencyKey } from "./announce-idempotency-DRIcQ039.js";
import { hasUsableSessionEntry } from "./subagent-announce-BH7YpLmx.js";
//#region src/agents/subagent-announce.requester-settle-wake.ts
/**
* Durable top-level requester settle wake delivery.
*
* Lifecycle owns the persisted outbox state on retained subagent run rows;
* this module selects a drained wave and delivers its synthesized wake.
*/
const subagentRegistryRuntimeLoader = createLazyImportLoader(() => import("./subagent-announce.registry.runtime.js"));
function loadSubagentRegistryRuntime() {
	return subagentRegistryRuntimeLoader.load();
}
let requesterSettleWakeDeps = { loadSubagentRegistryRuntime };
const REQUESTER_SETTLE_WAKE_MAX_ATTEMPTS = 3;
const REQUESTER_SETTLE_WAKE_MAX_AMBIGUOUS_REPLAYS = 3;
const REQUESTER_SETTLE_WAKE_RETRY_DELAYS_MS = [3e4, 12e4];
const activeRequesterSettleWakeBatches = /* @__PURE__ */ new Set();
function runIntervalsOverlap(a, b) {
	const aEnd = typeof a.endedAt === "number" ? a.endedAt : Number.MAX_SAFE_INTEGER;
	const bEnd = typeof b.endedAt === "number" ? b.endedAt : Number.MAX_SAFE_INTEGER;
	return a.createdAt <= bEnd && b.createdAt <= aEnd;
}
function buildRequesterSettleWakeMessage(params) {
	return [
		"[Subagent Context] Every subagent spawned from this session has now settled — none are still running or awaiting completion delivery.",
		"[Subagent Context] Do not keep waiting or call sessions_yield again for this batch; no further completion events will arrive.",
		"[Subagent Context] Review the completion results and send your consolidated final answer to the user now.",
		`[Subagent Context] Reply ONLY: ${SILENT_REPLY_TOKEN} only if you already delivered the consolidated final answer for this batch.`,
		"",
		params.findings ?? "(each child result was announced individually in earlier completion events)"
	].join("\n");
}
function buildConnectedSettledWave(candidates, settledEntry) {
	const unclaimed = new Set(candidates);
	const batch = [];
	const frontier = [settledEntry];
	for (const entry of unclaimed) if (entry.runId === settledEntry.runId) {
		unclaimed.delete(entry);
		batch.push(entry);
		frontier.push(entry);
		break;
	}
	for (let pivot = frontier.pop(); pivot; pivot = frontier.pop()) for (const entry of unclaimed) if (runIntervalsOverlap(entry, pivot)) {
		unclaimed.delete(entry);
		batch.push(entry);
		frontier.push(entry);
	}
	return batch;
}
function readSharedBatchState(batch) {
	const states = batch.map((entry) => entry.requesterSettleWake).filter((state) => Boolean(state));
	const source = states.find((state) => state.status === "dispatching") ?? states[0];
	return {
		status: source?.status ?? "pending",
		attemptCount: Math.max(0, ...states.map((state) => state.attemptCount)),
		...source?.replayCount !== void 0 ? { replayCount: source.replayCount } : {},
		...source?.nextAttemptAt !== void 0 ? { nextAttemptAt: source.nextAttemptAt } : {},
		...source?.batchRunIds ? { batchRunIds: [...source.batchRunIds] } : {},
		...source?.lastError !== void 0 ? { lastError: source.lastError } : {}
	};
}
function deferRequesterSettleWakeBatch(params) {
	params.transitionBatch(params.batchRunIds, {
		status: params.state.status,
		attemptCount: params.state.attemptCount,
		...params.state.replayCount !== void 0 ? { replayCount: params.state.replayCount } : {},
		nextAttemptAt: Math.max(params.state.nextAttemptAt ?? 0, Date.now() + REQUESTER_SETTLE_WAKE_RETRY_DELAYS_MS[0]),
		batchRunIds: [...params.batchRunIds],
		...params.state.lastError !== void 0 ? { lastError: params.state.lastError } : {}
	});
}
/**
* Wakes a registry-less top-level requester once its last spawned child
* reaches terminal settle. Durable state transitions happen synchronously
* through lifecycle-owned callbacks before and after every async delivery.
*/
async function maybeWakeRequesterAfterAllChildrenSettled(params) {
	if (params.signal?.aborted) return false;
	const requesterSessionKey = params.requesterSessionKey.trim();
	const initialState = params.settledEntry.requesterSettleWake;
	if (!requesterSessionKey || !initialState) return false;
	if (isCronSessionKey(requesterSessionKey)) {
		params.completeBatch([params.settledEntry.runId]);
		return false;
	}
	const registryRuntime = await requesterSettleWakeDeps.loadSubagentRegistryRuntime();
	const listedRuns = registryRuntime.listSubagentRunsForRequester(requesterSessionKey);
	const requesterRuns = Array.isArray(listedRuns) ? listedRuns : [];
	const currentSettledEntry = requesterRuns.find((entry) => entry.runId === params.settledEntry.runId) ?? params.settledEntry;
	if (!currentSettledEntry.requesterSettleWake) return false;
	const requesterHasUnsettledDescendants = () => registryRuntime.hasDescendantRunAwaitingSettle(requesterSessionKey, currentSettledEntry.runId);
	const frozenBatchRunIds = currentSettledEntry.requesterSettleWake.batchRunIds;
	let settledBatch;
	if (frozenBatchRunIds && frozenBatchRunIds.length > 0) {
		const runsById = new Map(requesterRuns.map((entry) => [entry.runId, entry]));
		settledBatch = frozenBatchRunIds.map((runId) => runsById.get(runId)).filter((entry) => Boolean(entry?.requesterSettleWake));
	} else settledBatch = buildConnectedSettledWave(requesterRuns.filter((entry) => entry.requesterSettleWake && hasSubagentRunEnded(entry)), currentSettledEntry);
	if (settledBatch.length === 0) return false;
	const batchRunIds = settledBatch.map((entry) => entry.runId).toSorted();
	if (requesterHasUnsettledDescendants()) {
		if (frozenBatchRunIds && frozenBatchRunIds.length > 0) deferRequesterSettleWakeBatch({
			batchRunIds,
			state: readSharedBatchState(settledBatch),
			transitionBatch: params.transitionBatch
		});
		return false;
	}
	const requiredSettled = settledBatch.filter((entry) => entry.expectsCompletionMessage === true);
	const hasUndeliveredRequiredCompletion = requiredSettled.some((entry) => entry.delivery?.status !== "delivered");
	if (requiredSettled.length === 0 || requiredSettled.length < 2 && !hasUndeliveredRequiredCompletion || getSubagentDepthFromSessionStore(requesterSessionKey) >= 1) {
		params.completeBatch(batchRunIds);
		return false;
	}
	const { entry: requesterEntry } = loadRequesterSessionEntry(requesterSessionKey);
	if (!hasUsableSessionEntry(requesterEntry)) {
		params.completeBatch(batchRunIds);
		return false;
	}
	const wakeMessage = buildRequesterSettleWakeMessage({ findings: buildChildCompletionFindings(dedupeLatestChildCompletionRows(filterCurrentDirectChildCompletionRows(settledBatch, {
		requesterSessionKey,
		getLatestSubagentRunByChildSessionKey: registryRuntime.getLatestSubagentRunByChildSessionKey
	}))) });
	const requesterSessionOrigin = normalizeDeliveryContext(params.requesterOrigin);
	const directOrigin = resolveAnnounceOrigin(requesterEntry, requesterSessionOrigin);
	const wakeKeyBase = `requester-settle:${requesterSessionKey}:${batchRunIds.join(",")}`;
	if (activeRequesterSettleWakeBatches.has(wakeKeyBase)) return false;
	activeRequesterSettleWakeBatches.add(wakeKeyBase);
	try {
		if (params.signal?.aborted) return false;
		let state = readSharedBatchState(settledBatch);
		if (!settledBatch.some((entry) => entry.requesterSettleWake)) return false;
		if ((state.nextAttemptAt ?? 0) > Date.now()) return false;
		if (requesterHasUnsettledDescendants()) {
			deferRequesterSettleWakeBatch({
				batchRunIds,
				state,
				transitionBatch: params.transitionBatch
			});
			return false;
		}
		let attemptIndex;
		if (state.status === "dispatching") attemptIndex = Math.max(0, state.attemptCount - 1);
		else {
			if (state.attemptCount >= REQUESTER_SETTLE_WAKE_MAX_ATTEMPTS) {
				params.completeBatch(batchRunIds);
				return false;
			}
			attemptIndex = state.attemptCount;
			state = {
				status: "dispatching",
				attemptCount: state.attemptCount + 1,
				batchRunIds
			};
			params.transitionBatch(batchRunIds, state);
		}
		let delivery;
		try {
			delivery = await deliverSubagentAnnouncement({
				requesterSessionKey,
				triggerMessage: wakeMessage,
				steerMessage: wakeMessage,
				summaryLine: "all spawned subagents settled",
				requesterSessionOrigin,
				requesterOrigin: requesterSessionOrigin,
				directOrigin,
				sourceSessionKey: currentSettledEntry.childSessionKey,
				sourceChannel: INTERNAL_MESSAGE_CHANNEL,
				sourceTool: "subagent_announce",
				targetRequesterSessionKey: requesterSessionKey,
				requesterIsSubagent: false,
				expectsCompletionMessage: false,
				directIdempotencyKey: buildAnnounceIdempotencyKey(attemptIndex === 0 ? wakeKeyBase : `${wakeKeyBase}:retry-${attemptIndex}`),
				signal: params.signal
			});
		} catch (error) {
			const lastError = error instanceof Error ? error.message : String(error);
			const replayCount = (state.replayCount ?? 0) + 1;
			const retryDelayMs = REQUESTER_SETTLE_WAKE_RETRY_DELAYS_MS[replayCount - 1];
			if (replayCount >= REQUESTER_SETTLE_WAKE_MAX_AMBIGUOUS_REPLAYS || retryDelayMs === void 0) {
				params.completeBatch(batchRunIds);
				return false;
			}
			const nextAttemptAt = Date.now() + retryDelayMs;
			state = {
				status: "dispatching",
				attemptCount: state.attemptCount,
				replayCount,
				nextAttemptAt,
				batchRunIds,
				lastError
			};
			params.transitionBatch(batchRunIds, state);
			logWarn(`requester settle wake transport replay ${replayCount} scheduled in ${Math.round(retryDelayMs / 1e3)}s: ${lastError}`);
			return false;
		}
		if (delivery.delivered) {
			params.completeBatch(batchRunIds);
			return true;
		}
		if (delivery.terminal === true || delivery.reason === "requester_abandoned") {
			params.completeBatch(batchRunIds);
			return false;
		}
		const attemptCount = attemptIndex + 1;
		const retryDelayMs = REQUESTER_SETTLE_WAKE_RETRY_DELAYS_MS[attemptIndex];
		if (attemptCount >= REQUESTER_SETTLE_WAKE_MAX_ATTEMPTS || retryDelayMs === void 0) {
			params.completeBatch(batchRunIds);
			return false;
		}
		const lastError = delivery.error ?? delivery.reason ?? "undelivered";
		const nextAttemptAt = Date.now() + retryDelayMs;
		params.transitionBatch(batchRunIds, {
			status: "pending",
			attemptCount,
			nextAttemptAt,
			batchRunIds,
			lastError
		});
		logWarn(`requester settle wake attempt ${attemptCount} failed; retrying in ${Math.round(retryDelayMs / 1e3)}s: ${lastError}`);
		return false;
	} finally {
		activeRequesterSettleWakeBatches.delete(wakeKeyBase);
	}
}
//#endregion
export { maybeWakeRequesterAfterAllChildrenSettled };
