import { useState } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api';
import { JobEditor } from '../src/components/JobEditor';
import type { Job } from '../src/types';
import fixture from '../../docs/examples/job.json';

function EditorWithDock({
  initial,
  onDirty = vi.fn(),
}: {
  initial: Job;
  onDirty?: (dirty: boolean) => void;
}) {
  const [dock, setDock] = useState<HTMLElement | null>(null);
  return (
    <>
      <JobEditor initial={initial} onSaved={vi.fn()} onDirty={onDirty} actionsContainer={dock} />
      <aside ref={setDock} aria-label="岗位快捷操作" />
    </>
  );
}

describe('JD quick actions', () => {
  beforeEach(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  it('keeps one set of actions in the dock and requires saving before confirming the new version', async () => {
    const initial = { ...structuredClone(fixture), confirmed: false } as Job;
    const saved = {
      ...initial,
      version: 2,
      content: { ...initial.content, title: '修改后的岗位' },
    };
    let finishSave!: (job: Job) => void;
    const save = vi.spyOn(api, 'saveJob').mockImplementation(
      () =>
        new Promise<Job>((resolve) => {
          finishSave = resolve;
        }),
    );
    const confirm = vi.spyOn(api, 'confirmJob').mockResolvedValue({ ...saved, confirmed: true });
    const dirty = vi.fn();
    render(<EditorWithDock initial={initial} onDirty={dirty} />);
    const dock = within(screen.getByRole('complementary', { name: '岗位快捷操作' }));
    const saveButton = dock.getByRole('button', { name: '保存 JD 新版本' });
    expect(screen.getAllByRole('button', { name: '保存 JD 新版本' })).toHaveLength(1);
    expect(saveButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText('岗位名称'), { target: { value: saved.content.title } });
    expect(dirty).toHaveBeenLastCalledWith(true);
    expect(dock.getByRole('button', { name: '确认 JD v1' })).toBeDisabled();
    fireEvent.click(saveButton);
    expect(save).toHaveBeenCalledWith(initial.id, {
      base_version: 1,
      raw_text: initial.raw_text,
      content: saved.content,
    });
    expect(screen.getByLabelText('岗位名称')).toBeDisabled();
    expect(saveButton).toBeDisabled();
    finishSave(saved);
    await waitFor(() => expect(dock.getByRole('button', { name: '确认 JD v2' })).toBeEnabled());
    expect(dirty).toHaveBeenLastCalledWith(false);
    fireEvent.click(dock.getByRole('button', { name: '确认 JD v2' }));
    await waitFor(() => expect(confirm).toHaveBeenCalledWith(initial.id, 2));
    await waitFor(() => expect(dock.getByRole('button', { name: '确认 JD v2' })).toBeDisabled());
  });

  it('focuses invalid input guidance and opens collapsed JD text when its validation link is used', () => {
    const save = vi.spyOn(api, 'saveJob');
    const initial = { ...structuredClone(fixture), confirmed: false } as Job;
    render(<EditorWithDock initial={initial} />);
    const raw = screen.getByLabelText('JD 原文');
    fireEvent.change(raw, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '保存 JD 新版本' }));
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByLabelText('岗位校验问题')).toHaveFocus();
    expect(raw.closest('details')).not.toHaveAttribute('open');
    fireEvent.click(screen.getByRole('link', { name: 'JD 需为 1–20,000 字符。' }));
    expect(raw.closest('details')).toHaveAttribute('open');
    expect(raw).toHaveFocus();
    expect(raw.scrollIntoView).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '确认 JD v1' })).toBeDisabled();
  });

  it('shows API failures beside the quick actions without discarding unsaved edits', async () => {
    const initial = { ...structuredClone(fixture), confirmed: false } as Job;
    vi.spyOn(api, 'saveJob').mockRejectedValue(new Error('保存暂时失败'));
    render(<EditorWithDock initial={initial} />);
    fireEvent.change(screen.getByLabelText('岗位名称'), { target: { value: '仍需保留的修改' } });
    fireEvent.click(screen.getByRole('button', { name: '保存 JD 新版本' }));
    const dock = within(screen.getByRole('complementary', { name: '岗位快捷操作' }));
    expect(await dock.findByRole('alert')).toHaveTextContent('保存暂时失败');
    expect(screen.getByLabelText('岗位名称')).toHaveValue('仍需保留的修改');
    expect(dock.getByRole('button', { name: '确认 JD v1' })).toBeDisabled();
    expect(dock.getByRole('button', { name: '保存 JD 新版本' })).toBeEnabled();
  });
});
