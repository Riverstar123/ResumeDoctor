import { act, render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { AppProvider, useApp } from '../src/state';
import type { Profile } from '../src/types';
import profileFixture from '../../docs/examples/profile.json';

let current: ReturnType<typeof useApp>;
function Consumer() {
  current = useApp();
  return null;
}
beforeEach(() => sessionStorage.clear());
describe('volatile follow-up drafts', () => {
  it.each(['expired', 'deleted'])('clears unsent content when the session is %s', async (event) => {
    vi.spyOn(api, 'deleteSession').mockResolvedValue(undefined);
    render(
      <AppProvider>
        <Consumer />
      </AppProvider>,
    );
    const drafts = current.followUpDrafts;
    drafts.set('target', {
      resource: profileFixture as Profile,
      draft: profileFixture.content as Profile['content'],
      answer: 'UNSENT_SYNTHETIC_ANSWER',
      question: '',
      taskId: null,
      appliedTaskId: '',
    });
    expect(JSON.stringify(sessionStorage)).not.toContain('UNSENT_SYNTHETIC_ANSWER');
    await act(async () => {
      if (event === 'expired') window.dispatchEvent(new Event('rd:session-expired'));
      else await current.remove();
    });
    await waitFor(() => expect(drafts.size).toBe(0));
    expect(current.followUpDrafts.size).toBe(0);
  });
});
