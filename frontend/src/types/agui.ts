/**
 * AG-UI 1.0 event envelope types used by TraceWise.
 * These are a deliberately small typed subset for this UI. Validate the complete
 * producer against the upstream AG-UI 1.0 JSON Schema before production rollout.
 */
export type AGUIEventType =
  | 'RUN_STARTED' | 'RUN_FINISHED' | 'RUN_ERROR'
  | 'STEP_STARTED' | 'STEP_FINISHED'
  | 'TEXT_MESSAGE_START' | 'TEXT_MESSAGE_CONTENT' | 'TEXT_MESSAGE_END'
  | 'TOOL_CALL_START' | 'TOOL_CALL_ARGS' | 'TOOL_CALL_END' | 'TOOL_CALL_RESULT'
  | 'STATE_SNAPSHOT' | 'STATE_DELTA' | 'ACTIVITY_SNAPSHOT' | 'ACTIVITY_DELTA'
  | 'SUBAGENT_STARTED' | 'SUBAGENT_FINISHED' | 'SUBAGENT_ERROR' | 'CUSTOM';

export interface AGUIEvent {
  type: AGUIEventType;
  timestamp?: number;
  threadId?: string;
  runId?: string;
  [key: string]: unknown;
}

export interface TraceWiseCustomEvent extends AGUIEvent {
  type: 'CUSTOM';
  name: 'tracewise.activity' | 'tracewise.stage' | 'tracewise.artifact' | 'tracewise.claim' | 'tracewise.review' | 'tracewise.agent';
  value: Record<string, unknown>;
}
