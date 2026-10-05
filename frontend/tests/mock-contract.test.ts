// @vitest-environment node
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import contract from '../../docs/api/openapi.json';
import profileExample from '../../docs/examples/profile.json';
import { ApiClient } from '../src/api/client';
import { demoJob, demoText, mockFetch, setScenario } from '../src/api/mock';
import { emptyProfile } from '../src/validation';
import type { ProfileContent, Schema } from '../src/types';

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
function schema(name: keyof Schema, value: unknown) {
  const validate = ajv.compile({
    $ref: `#/components/schemas/${name}`,
    components: contract.components,
  });
  expect(validate(value), JSON.stringify(validate.errors)).toBe(true);
}
let client: ApiClient;
beforeEach(() => {
  const store = new Map<string, string>();
  vi.stubGlobal('sessionStorage', {
    getItem: (key: string) => store.get(key) || null,
    setItem: (key: string, value: string) => store.set(key, value),
    removeItem: (key: string) => store.delete(key),
  });
  vi.useFakeTimers();
  client = new ApiClient(mockFetch);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
async function settle(id: string) {
  vi.advanceTimersByTime(1000);
  const task = await client.task(id);
  schema('Task', task);
  return task;
}
async function confirmedInputs() {
  schema('Session', await client.session());
  schema('ModelList', await client.models());
  const profile = await client.createProfile(
    profileExample.content as ProfileContent,
    crypto.randomUUID(),
  );
  const confirmed = await client.confirmProfile(profile.id, profile.version);
  schema('Profile', confirmed);
  const accepted = await client.createJob(
    { raw_text: demoJob, company_context: '', model_id: 'demo-model-a' },
    crypto.randomUUID(),
  );
  schema('TaskAccepted', accepted);
  const task = await settle(accepted.task_id);
  const job = await client.job(task.result!.resource_id);
  const confirmedJob = await client.confirmJob(job.id, job.version);
  schema('Job', confirmedJob);
  return {
    profile: { id: profile.id, version: profile.version },
    jobs: [{ id: job.id, version: job.version }],
    model_id: 'demo-model-a',
  };
}
describe('mock responses conform to repository OpenAPI', () => {
  it('normal, partial and failure responses preserve status invariants', async () => {
    const input = await confirmedInputs();
    for (const scenario of ['success', 'partial', 'failed'] as const) {
      setScenario(scenario);
      const accepted = await client.diagnose(input, crypto.randomUUID());
      schema('DiagnosisAccepted', accepted);
      const pending = await client.task(accepted.task_id);
      schema('Task', pending);
      expect(pending.result).toBeNull();
      await settle(accepted.task_id);
      const d = await client.diagnosis(accepted.diagnosis_id);
      schema('Diagnosis', d);
      expect(d.status).toBe(scenario === 'success' ? 'succeeded' : scenario);
      if (scenario === 'failed') {
        expect(d.items[0].score_result).toBeNull();
        await expect(client.export(d.id)).rejects.toMatchObject({ status: 409 });
      } else {
        expect(d.items[0].score_result?.score).toBe(66.7);
        expect(await client.export(d.id)).toContain('coverage-v1');
      }
    }
  });
  it('conversation keeps messages and immutable historical versions', async () => {
    await client.session();
    const profile = await client.createProfile(emptyProfile(), crypto.randomUUID());
    const accepted = await client.sendMessage(
      profile.id,
      { content: demoText, base_version: 1, model_id: 'demo-model-a' },
      crypto.randomUUID(),
    );
    await settle(accepted.task_id);
    const messages = await client.messages(profile.id);
    schema('MessageList', messages);
    expect(messages.items[0].content).toBe(demoText);
    expect((await client.profile(profile.id, 1)).content.facts).toHaveLength(0);
    expect((await client.profile(profile.id)).version).toBe(2);
  });
  it('deduplicates accepted requests and rejects changed payloads on the same key', async () => {
    const input = await confirmedInputs();
    const key = crypto.randomUUID();
    const first = await client.diagnose(input, key);
    expect(await client.diagnose(input, key)).toEqual(first);
    await expect(
      client.diagnose({ ...input, model_id: 'demo-model-b' }, key),
    ).rejects.toMatchObject({ status: 409, code: 'IDEMPOTENCY_CONFLICT' });
  });
  it('fixed models do not rewrite previous reports, and deletion invalidates old resources', async () => {
    const input = await confirmedInputs();
    const first = await client.diagnose(input, crypto.randomUUID());
    await settle(first.task_id);
    const old = await client.diagnosis(first.diagnosis_id);
    const second = await client.diagnose(
      { ...input, model_id: 'demo-model-b' },
      crypto.randomUUID(),
    );
    await settle(second.task_id);
    expect(await client.diagnosis(first.diagnosis_id)).toEqual(old);
    expect((await client.diagnosis(second.diagnosis_id)).items[0].score_result).toEqual(
      old.items[0].score_result,
    );
    await client.deleteSession();
    await expect(client.diagnosis(old.id)).rejects.toMatchObject({ status: 401 });
    await client.session();
    await expect(client.diagnosis(old.id)).rejects.toMatchObject({ status: 404 });
  });
  it('handles no scorable requirements, unconfirmed versions and duplicate job versions', async () => {
    const input = await confirmedInputs();
    const job = await client.job(input.jobs[0].id);
    const draft = await client.saveJob(job.id, {
      base_version: job.version,
      raw_text: job.raw_text,
      content: {
        ...job.content,
        requirements: job.content.requirements.map((r) => ({
          ...r,
          ignored: true,
          ignore_reason: '演示忽略',
        })),
      },
    });
    input.jobs[0].version = draft.version;
    await expect(client.diagnose(input, crypto.randomUUID())).rejects.toMatchObject({
      code: 'UNCONFIRMED_VERSION',
    });
    await client.confirmJob(job.id, draft.version);
    await expect(client.diagnose(input, crypto.randomUUID())).rejects.toMatchObject({
      code: 'NO_SCORABLE_REQUIREMENTS',
    });
    await expect(
      client.diagnose({ ...input, jobs: [input.jobs[0], input.jobs[0]] }, crypto.randomUUID()),
    ).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
  });
});
