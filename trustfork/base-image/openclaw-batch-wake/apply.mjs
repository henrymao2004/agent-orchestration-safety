#!/usr/bin/env node
// Patches openclaw@2026.7.1-2 so a top-level requester is woken once all of
// its spawned children have settled, with their results delivered together.
// Source: openclaw/openclaw commit eb4f3d792f416df4f24f1dd4037b14d79891b6ba.
//
// Usage: node apply.mjs <openclaw package dir>
// Every anchor must match exactly. A marker with file hashes makes reruns no-ops.
import { createHash } from "node:crypto"
import { copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const PINNED_VERSION = "2026.7.1-2"
const MODULE_NAME = "subagent-announce.requester-settle-wake.js"
const here = path.dirname(fileURLToPath(import.meta.url))
const packageDir = process.argv[2]
if (!packageDir) {
	console.error("usage: node apply.mjs <openclaw package dir>")
	process.exit(2)
}
const pkg = JSON.parse(readFileSync(path.join(packageDir, "package.json"), "utf8"))
if (pkg.name !== "openclaw" || pkg.version !== PINNED_VERSION) {
	console.error(`expected openclaw@${PINNED_VERSION}, found ${pkg.name}@${pkg.version}`)
	process.exit(1)
}
const dist = path.join(packageDir, "dist")

const PATCHES = [
	{
		file: "subagent-announce-BH7YpLmx.js",
		label: "subagent-announce.ts: export hasUsableSessionEntry",
		count: 1,
		find: `export { testing as __testing, testing, buildSubagentSystemPrompt, captureSubagentCompletionReply, runSubagentAnnounceFlow };`,
		replace: `export { testing as __testing, testing, buildSubagentSystemPrompt, captureSubagentCompletionReply, hasUsableSessionEntry, runSubagentAnnounceFlow };`,
	},
	{
		file: "subagent-registry-state-CP7kKu69.js",
		label: "subagent-registry-queries.ts: forEachDescendantRun early stop",
		count: 1,
		find: `			visitor(runId, entry);
			const childKey = entry.childSessionKey.trim();
`,
		replace: `			if (visitor(runId, entry) === true) return true;
			const childKey = entry.childSessionKey.trim();
`,
	},
	{
		file: "subagent-registry-state-CP7kKu69.js",
		label: "subagent-registry-queries.ts: countPendingDescendantRunsInternal options",
		count: 1,
		find: `function countPendingDescendantRunsInternal(runs, rootSessionKey, excludeRunId) {
	const excludedRunId = excludeRunId?.trim();
	let count = 0;
	if (!forEachDescendantRun(runs, rootSessionKey, (runId, entry) => {
		const runEnded = hasSubagentRunEnded(entry);
		const cleanupCompleted = typeof entry.cleanupCompletedAt === "number";
		if ((runEnded ? !cleanupCompleted : isLiveUnendedSubagentRun(entry)) && runId !== excludedRunId) count += 1;
	})) return 0;
	return count;
}`,
		replace: `function countPendingDescendantRunsInternal(runs, rootSessionKey, options) {
	const excludedRunId = options?.excludeRunId?.trim();
	let count = 0;
	if (!forEachDescendantRun(runs, rootSessionKey, (runId, entry) => {
		if (runId === excludedRunId) return;
		if (hasSubagentRunEnded(entry) ? typeof entry.cleanupCompletedAt !== "number" && !(options?.treatSuspendedDeliveryAsSettled === true && isDeliverySuspended(entry)) : isLiveUnendedSubagentRun(entry)) {
			count += 1;
			if (options?.stopAtFirst === true) return true;
		}
	})) return 0;
	return count;
}`,
	},
	{
		file: "subagent-registry-state-CP7kKu69.js",
		label: "subagent-registry-queries.ts: hasDescendantRunAwaitingSettleFromRuns",
		count: 1,
		find: `	return countPendingDescendantRunsInternal(runs, rootSessionKey, excludeRunId);
}
`,
		replace: `	return countPendingDescendantRunsInternal(runs, rootSessionKey, { excludeRunId });
}
/**
* True when any descendant below a root session has not reached a terminal
* settle. Differs from the pending count in one way: a run whose final
* delivery was suspended counts as settled — suspension is terminal for
* automatic announce retries, so requester-drain decisions must not wait on it.
*/
function hasDescendantRunAwaitingSettleFromRuns(runs, rootSessionKey, excludeRunId) {
	return countPendingDescendantRunsInternal(runs, rootSessionKey, {
		excludeRunId,
		treatSuspendedDeliveryAsSettled: true,
		stopAtFirst: true
	}) > 0;
}
`,
	},
	{
		file: "subagent-registry-state-CP7kKu69.js",
		label: "subagent-registry-state: export hasDescendantRunAwaitingSettleFromRuns",
		count: 1,
		find: `export { getSubagentSessionRuntimeMs as A, `,
		replace: `export { hasDescendantRunAwaitingSettleFromRuns, getSubagentSessionRuntimeMs as A, `,
	},
	{
		file: "subagent-announce.registry.runtime-CSBLo3Ip.js",
		label: "subagent-registry-announce-read.ts: import",
		count: 1,
		find: `import { C as resolveRequesterForChildSessionFromRuns, `,
		replace: `import { hasDescendantRunAwaitingSettleFromRuns, C as resolveRequesterForChildSessionFromRuns, `,
	},
	{
		file: "subagent-announce.registry.runtime-CSBLo3Ip.js",
		label: "subagent-registry-announce-read.ts: hasDescendantRunAwaitingSettle",
		count: 1,
		find: `	return countPendingDescendantRunsExcludingRunFromRuns(getSubagentRunsSnapshotForRead(subagentRuns), rootSessionKey, excludeRunId);
}
//#endregion
export { countActiveDescendantRuns, countPendingDescendantRuns, countPendingDescendantRunsExcludingRun, getLatestSubagentRunByChildSessionKey, isSubagentSessionRunActive,`,
		replace: `	return countPendingDescendantRunsExcludingRunFromRuns(getSubagentRunsSnapshotForRead(subagentRuns), rootSessionKey, excludeRunId);
}
/** True when any descendant run still awaits terminal settle (suspended delivery counts as settled). */
function hasDescendantRunAwaitingSettle(rootSessionKey, excludeRunId) {
	return hasDescendantRunAwaitingSettleFromRuns(getSubagentRunsSnapshotForRead(subagentRuns), rootSessionKey, excludeRunId);
}
//#endregion
export { countActiveDescendantRuns, countPendingDescendantRuns, countPendingDescendantRunsExcludingRun, getLatestSubagentRunByChildSessionKey, hasDescendantRunAwaitingSettle, isSubagentSessionRunActive,`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry-helpers.ts: keep settle-wake rows during restore reconcile",
		count: 1,
		find: `	for (const [runId, entry] of params.runs.entries()) {
		if (entry.killReconciliation) continue;`,
		replace: `	for (const [runId, entry] of params.runs.entries()) {
		if (entry.requesterSettleWake) continue;
		if (entry.killReconciliation) continue;`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry-lifecycle.ts: settle-wake scheduler state",
		count: 1,
		find: `function createSubagentRegistryLifecycleController(params) {
	const scheduledResumeTimers = /* @__PURE__ */ new Set();
`,
		replace: `function createSubagentRegistryLifecycleController(params) {
	const scheduledResumeTimers = /* @__PURE__ */ new Set();
	const scheduledRequesterSettleWakeRuns = /* @__PURE__ */ new Set();
	const scheduledRequesterSettleWakeTimers = /* @__PURE__ */ new Map();
`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry-lifecycle.ts: clear settle-wake timers",
		count: 1,
		find: `		for (const timer of scheduledResumeTimers) clearTimeout(timer);
		scheduledResumeTimers.clear();
`,
		replace: `		for (const timer of scheduledResumeTimers) clearTimeout(timer);
		scheduledResumeTimers.clear();
		for (const timer of scheduledRequesterSettleWakeTimers.values()) clearTimeout(timer);
		scheduledRequesterSettleWakeTimers.clear();
`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry-lifecycle.ts: settle-wake outbox transitions and scheduler",
		count: 1,
		find: `	const suspendPendingFinalDelivery = (args) => {
		markPendingFinalDelivery({`,
		replace: `	const transitionRequesterSettleWakeBatch = (runIds, state) => {
		const entries = runIds.map((runId) => params.runs.get(runId)).filter((entry) => Boolean(entry?.requesterSettleWake));
		const previousStates = entries.map((entry) => structuredClone(entry.requesterSettleWake));
		for (const entry of entries) entry.requesterSettleWake = {
			...state,
			...entry.requesterSettleWake?.retireAfterSettle === true ? { retireAfterSettle: true } : {}
		};
		try {
			params.persistOrThrow();
		} catch (error) {
			entries.forEach((entry, index) => {
				entry.requesterSettleWake = previousStates[index];
			});
			throw error;
		}
	};
	const completeRequesterSettleWakeBatch = (runIds) => {
		const entries = runIds.map((runId) => [runId, params.runs.get(runId)]).filter((pair) => Boolean(pair[1]?.requesterSettleWake));
		const requesterSessionKeys = new Set(entries.map(([, entry]) => entry.requesterSessionKey));
		const previousStates = entries.map(([, entry]) => structuredClone(entry.requesterSettleWake));
		for (const [runId, entry] of entries) if (entry.requesterSettleWake?.retireAfterSettle === true) params.runs.delete(runId);
		else entry.requesterSettleWake = void 0;
		try {
			params.persistOrThrow();
		} catch (error) {
			entries.forEach(([runId, entry], index) => {
				params.runs.set(runId, entry);
				entry.requesterSettleWake = previousStates[index];
			});
			throw error;
		}
		for (const [runId, entry] of entries) {
			const retryTimer = scheduledRequesterSettleWakeTimers.get(runId);
			if (retryTimer) {
				clearTimeout(retryTimer);
				scheduledRequesterSettleWakeTimers.delete(runId);
			}
			if (entry.requesterSettleWake === void 0 || !params.runs.has(runId)) {
				params.resumedRuns.delete(runId);
				params.clearPendingLifecycleError(runId);
			}
		}
		for (const [runId, entry] of params.runs) if (entry.requesterSettleWake && requesterSessionKeys.has(entry.requesterSessionKey)) scheduleRequesterSettleWake(runId, entry);
	};
	const markRequesterSettleWakePending = (entry, options) => {
		const existing = entry.requesterSettleWake;
		entry.requesterSettleWake = {
			status: existing?.status ?? "pending",
			attemptCount: existing?.attemptCount ?? 0,
			...existing?.replayCount !== void 0 ? { replayCount: existing.replayCount } : {},
			...existing?.nextAttemptAt !== void 0 ? { nextAttemptAt: existing.nextAttemptAt } : {},
			...existing?.batchRunIds ? { batchRunIds: [...existing.batchRunIds] } : {},
			...existing?.lastError !== void 0 ? { lastError: existing.lastError } : {},
			...existing?.retireAfterSettle === true || options?.retireAfterSettle === true ? { retireAfterSettle: true } : {}
		};
	};
	const persistRequesterSettleWakePending = (entry, options) => {
		const previousCleanupCompletedAt = entry.cleanupCompletedAt;
		const previousWake = structuredClone(entry.requesterSettleWake);
		if (options?.cleanupCompletedAt !== void 0) entry.cleanupCompletedAt = options.cleanupCompletedAt;
		markRequesterSettleWakePending(entry, options);
		try {
			params.persistOrThrow();
		} catch (error) {
			entry.cleanupCompletedAt = previousCleanupCompletedAt;
			entry.requesterSettleWake = previousWake;
			throw error;
		}
	};
	function scheduleRequesterSettleWakeRetry(runId, entry) {
		const nextAttemptAt = entry.requesterSettleWake?.nextAttemptAt;
		if (nextAttemptAt === void 0 || nextAttemptAt <= Date.now() || scheduledRequesterSettleWakeTimers.has(runId)) return;
		const timer = setTimeout(() => {
			scheduledRequesterSettleWakeTimers.delete(runId);
			const current = params.runs.get(runId);
			if (current === entry && current.requesterSettleWake) scheduleRequesterSettleWake(runId, current);
		}, Math.max(0, nextAttemptAt - Date.now()));
		timer.unref?.();
		scheduledRequesterSettleWakeTimers.set(runId, timer);
	}
	function scheduleRequesterSettleWake(runId, entry) {
		const requesterSessionKey = entry.requesterSessionKey?.trim();
		if (!requesterSessionKey || scheduledRequesterSettleWakeRuns.has(runId) || scheduledRequesterSettleWakeTimers.has(runId)) return;
		if ((entry.requesterSettleWake?.nextAttemptAt ?? 0) > Date.now()) {
			scheduleRequesterSettleWakeRetry(runId, entry);
			return;
		}
		scheduledRequesterSettleWakeRuns.add(runId);
		runWithGatewayIndependentRootWorkContinuation(() => params.maybeWakeRequesterAfterAllChildrenSettled({
			requesterSessionKey,
			requesterOrigin: entry.requesterOrigin,
			settledEntry: entry,
			transitionBatch: transitionRequesterSettleWakeBatch,
			completeBatch: completeRequesterSettleWakeBatch
		})).catch((error) => {
			params.warn("requester settle wake failed", {
				error: buildSafeLifecycleErrorMeta(error),
				runId: maskRunId(runId),
				requesterSessionKey: maskSessionKey(requesterSessionKey)
			});
		}).finally(() => {
			scheduledRequesterSettleWakeRuns.delete(runId);
			const current = params.runs.get(runId);
			if (current === entry && current.requesterSettleWake) scheduleRequesterSettleWakeRetry(runId, current);
		});
	}
	const suspendPendingFinalDelivery = (args) => {
		const previousEntry = structuredClone(args.entry);
		markPendingFinalDelivery({`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry-lifecycle.ts: suspended delivery settles the child",
		count: 1,
		find: `		logAnnounceGiveUp(args.entry, args.reason);
		params.persist();
	};
`,
		replace: `		logAnnounceGiveUp(args.entry, args.reason);
		markRequesterSettleWakePending(args.entry);
		try {
			params.persistOrThrow();
		} catch (error) {
			const mutableEntry = args.entry;
			for (const key of Object.keys(mutableEntry)) delete mutableEntry[key];
			Object.assign(args.entry, previousEntry);
			throw error;
		}
		scheduleRequesterSettleWake(args.runId, args.entry);
	};
`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry-lifecycle.ts: completeCleanupBookkeeping schedules the settle wake",
		count: 1,
		find: `		if (cleanupParams.cleanup === "delete") {
			params.clearPendingLifecycleError(cleanupParams.runId);
			if (!cleanupParams.provisionalKill) params.notifyContextEngineSubagentEnded({
				childSessionKey: cleanupParams.entry.childSessionKey,
				reason: "deleted",
				agentDir: cleanupParams.entry.agentDir,
				workspaceDir: cleanupParams.entry.workspaceDir
			});
			params.runs.delete(cleanupParams.runId);
			params.persist();
			retryDeferredCompletedAnnounces(cleanupParams.runId);
			return;
		}
		if (!cleanupParams.provisionalKill) params.notifyContextEngineSubagentEnded({
			childSessionKey: cleanupParams.entry.childSessionKey,
			reason: "completed",
			agentDir: cleanupParams.entry.agentDir,
			workspaceDir: cleanupParams.entry.workspaceDir
		});
		if (cleanupParams.entry.endedReason === "subagent-killed" && cleanupParams.entry.suppressAnnounceReason !== "killed") {
			params.clearPendingLifecycleError(cleanupParams.runId);
			params.runs.delete(cleanupParams.runId);
			params.persist();
			retryDeferredCompletedAnnounces(cleanupParams.runId);
			return;
		}
		if (!cleanupParams.provisionalKill) cleanupParams.entry.cleanupCompletedAt = cleanupParams.completedAt;
		params.persist();
		retryDeferredCompletedAnnounces(cleanupParams.runId);
	};
`,
		replace: `		if (cleanupParams.cleanup === "delete") {
			params.clearPendingLifecycleError(cleanupParams.runId);
			if (!cleanupParams.provisionalKill) params.notifyContextEngineSubagentEnded({
				childSessionKey: cleanupParams.entry.childSessionKey,
				reason: "deleted",
				agentDir: cleanupParams.entry.agentDir,
				workspaceDir: cleanupParams.entry.workspaceDir
			});
			if (cleanupParams.provisionalKill || cleanupParams.skipRequesterSettleWake) {
				params.runs.delete(cleanupParams.runId);
				params.persist();
				retryDeferredCompletedAnnounces(cleanupParams.runId);
				return;
			}
			persistRequesterSettleWakePending(cleanupParams.entry, {
				cleanupCompletedAt: cleanupParams.completedAt,
				retireAfterSettle: true
			});
			retryDeferredCompletedAnnounces(cleanupParams.runId);
			scheduleRequesterSettleWake(cleanupParams.runId, cleanupParams.entry);
			return;
		}
		if (!cleanupParams.provisionalKill) params.notifyContextEngineSubagentEnded({
			childSessionKey: cleanupParams.entry.childSessionKey,
			reason: "completed",
			agentDir: cleanupParams.entry.agentDir,
			workspaceDir: cleanupParams.entry.workspaceDir
		});
		if (cleanupParams.entry.endedReason === "subagent-killed" && cleanupParams.entry.suppressAnnounceReason !== "killed") {
			params.clearPendingLifecycleError(cleanupParams.runId);
			if (cleanupParams.provisionalKill || cleanupParams.skipRequesterSettleWake) {
				params.runs.delete(cleanupParams.runId);
				params.persist();
				retryDeferredCompletedAnnounces(cleanupParams.runId);
				return;
			}
			persistRequesterSettleWakePending(cleanupParams.entry, {
				cleanupCompletedAt: cleanupParams.completedAt,
				retireAfterSettle: true
			});
			retryDeferredCompletedAnnounces(cleanupParams.runId);
			scheduleRequesterSettleWake(cleanupParams.runId, cleanupParams.entry);
			return;
		}
		if (!cleanupParams.provisionalKill && !cleanupParams.skipRequesterSettleWake) persistRequesterSettleWakePending(cleanupParams.entry, { cleanupCompletedAt: cleanupParams.completedAt });
		else {
			if (!cleanupParams.provisionalKill) cleanupParams.entry.cleanupCompletedAt = cleanupParams.completedAt;
			params.persist();
		}
		retryDeferredCompletedAnnounces(cleanupParams.runId);
		if (!cleanupParams.provisionalKill && !cleanupParams.skipRequesterSettleWake) scheduleRequesterSettleWake(cleanupParams.runId, cleanupParams.entry);
	};
`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry-lifecycle.ts: keep delete-mode result text for the settle wake",
		count: 1,
		find: `			if (cleanup === "delete") {
				completion.resultText = void 0;
				completion.capturedAt = void 0;
			}
			completeCleanupBookkeeping({`,
		replace: `			completeCleanupBookkeeping({`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry-lifecycle.ts: expose resumeRequesterSettleWake",
		count: 1,
		find: `		refreshFrozenResultFromSession,
		startSubagentAnnounceCleanupFlow
	};
}`,
		replace: `		refreshFrozenResultFromSession,
		resumeRequesterSettleWake: scheduleRequesterSettleWake,
		startSubagentAnnounceCleanupFlow
	};
}`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry-run-manager.ts: fresh runs carry no settle-wake state",
		count: 2,
		find: `			wakeOnDescendantSettle: void 0,
`,
		replace: `			wakeOnDescendantSettle: void 0,
			requesterSettleWake: void 0,
`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry.ts: settle-wake dependency",
		count: 1,
		find: `	runSubagentAnnounceFlow: async (params) => (await loadSubagentAnnounceModule()).runSubagentAnnounceFlow(params)
};`,
		replace: `	runSubagentAnnounceFlow: async (params) => (await loadSubagentAnnounceModule()).runSubagentAnnounceFlow(params),
	maybeWakeRequesterAfterAllChildrenSettled: async (params) => (await import("./subagent-announce.requester-settle-wake.js")).maybeWakeRequesterAfterAllChildrenSettled(params)
};`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry.ts: controller wiring",
		count: 1,
		find: `const { clearScheduledResumeTimers, completeCleanupBookkeeping, completeSubagentRun, finalizeResumedAnnounceGiveUp, refreshFrozenResultFromSession, startSubagentAnnounceCleanupFlow } = createSubagentRegistryLifecycleController({`,
		replace: `const { clearScheduledResumeTimers, completeCleanupBookkeeping, completeSubagentRun, finalizeResumedAnnounceGiveUp, refreshFrozenResultFromSession, resumeRequesterSettleWake, startSubagentAnnounceCleanupFlow } = createSubagentRegistryLifecycleController({`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry.ts: controller dependency",
		count: 1,
		find: `	runSubagentAnnounceFlow: (params) => subagentRegistryDeps.runSubagentAnnounceFlow(params),
	warn: (message, meta) => log.warn(message, meta)
});`,
		replace: `	runSubagentAnnounceFlow: (params) => subagentRegistryDeps.runSubagentAnnounceFlow(params),
	maybeWakeRequesterAfterAllChildrenSettled: (args) => subagentRegistryDeps.maybeWakeRequesterAfterAllChildrenSettled(args),
	warn: (message, meta) => log.warn(message, meta)
});`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry.ts: resume replays a pending settle wake",
		count: 1,
		find: `	if (!entry) return;
	if (entry.cleanupCompletedAt) return;
`,
		replace: `	if (!entry) return;
	if (entry.requesterSettleWake) {
		resumeRequesterSettleWake(runId, entry);
		return;
	}
	if (entry.cleanupCompletedAt) return;
`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry.ts: discarded suspended delivery skips the settle wake",
		count: 1,
		find: `	completeCleanupBookkeeping({
		runId,
		entry,
		cleanup: entry.cleanup,
		completedAt: now
	});`,
		replace: `	completeCleanupBookkeeping({
		runId,
		entry,
		cleanup: entry.cleanup,
		completedAt: now,
		skipRequesterSettleWake: true
	});`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "subagent-registry.ts: sweeper resumes pending settle wakes",
		count: 1,
		find: `		for (const [runId, entry] of subagentRuns.entries()) {
			if (isSuspendedPendingFinalDelivery(entry)) {`,
		replace: `		for (const [runId, entry] of subagentRuns.entries()) {
			if (entry.requesterSettleWake) {
				resumeRequesterSettleWake(runId, entry);
				continue;
			}
			if (isSuspendedPendingFinalDelivery(entry)) {`,
	},
	{
		file: "subagent-registry-DexSZ4w1.js",
		label: "gateway-work-admission.ts: continuation wrapper for the pinned build",
		count: 1,
		find: `function createSubagentRegistryLifecycleController(params) {
`,
		replace: `async function runWithGatewayIndependentRootWorkContinuation(run) {
	return await run();
}
function createSubagentRegistryLifecycleController(params) {
`,
	},
]

const MARKER = path.join(dist, ".trustfork-batch-wake.json")
const sha256 = (file) => createHash("sha256").update(readFileSync(path.join(dist, file))).digest("hex")
const patchedFiles = [...new Set(PATCHES.map((patch) => patch.file)), MODULE_NAME]

if (existsSync(MARKER)) {
	const marker = JSON.parse(readFileSync(MARKER, "utf8"))
	const drifted = patchedFiles.filter((file) => marker.sha256?.[file] !== sha256(file))
	if (drifted.length) throw new Error(`patched OpenClaw files changed after backport: ${drifted.join(", ")}`)
	console.log(JSON.stringify({ ...marker, status: "already-applied" }, null, 2))
	process.exit(0)
}

function countOf(text, needle) {
	let count = 0
	for (let index = text.indexOf(needle); index >= 0; index = text.indexOf(needle, index + needle.length)) count += 1
	return count
}

const files = new Map()
for (const patch of PATCHES) {
	if (!files.has(patch.file)) files.set(patch.file, readFileSync(path.join(dist, patch.file), "utf8"))
	const text = files.get(patch.file)
	const found = countOf(text, patch.find)
	if (found !== patch.count) throw new Error(`anchor mismatch for ${patch.label} in ${patch.file}: found ${found}, expected ${patch.count}`)
	files.set(patch.file, text.split(patch.find).join(patch.replace))
}
if (existsSync(path.join(dist, MODULE_NAME))) throw new Error(`dist/${MODULE_NAME} already exists without a backport marker`)
for (const [file, text] of files) writeFileSync(path.join(dist, file), text)
copyFileSync(path.join(here, MODULE_NAME), path.join(dist, MODULE_NAME))
const marker = {
	upstream: "openclaw/openclaw@eb4f3d792f416df4f24f1dd4037b14d79891b6ba (openclaw@2026.7.2-beta.3)",
	version: pkg.version,
	patches: PATCHES.map((patch) => patch.label),
	sha256: Object.fromEntries(patchedFiles.map((file) => [file, sha256(file)])),
}
writeFileSync(MARKER, `${JSON.stringify(marker, null, 2)}\n`)
console.log(JSON.stringify({ ...marker, status: "applied" }, null, 2))
