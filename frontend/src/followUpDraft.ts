import type { Profile } from './types';

// Volatile, session-scoped UI state. Never written to storage or submitted automatically.
export type FollowUpDraft = {
  resource: Profile;
  draft: Profile['content'];
  answer: string;
  question: string;
  taskId: string | null;
  appliedTaskId: string;
};
