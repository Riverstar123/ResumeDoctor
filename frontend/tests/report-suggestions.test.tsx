import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReportSuggestions } from '../src/components/ReportSuggestions';
import type { Schema } from '../src/types';

const suggestions: Schema['Suggestion'][] = [
  {
    requirement_id: 'r1',
    original: '参与课程项目。',
    revised: '使用 Python 完成课程项目的数据清洗。',
    rationale: '明确已有的工具与任务。',
    evidence_ids: ['e1'],
    requires_user_input: false,
  },
  {
    requirement_id: 'r2',
    original: null,
    revised: '在 [项目] 中负责 [具体任务]。',
    rationale: '尚需核实实际承担的工作。',
    evidence_ids: [],
    requires_user_input: true,
  },
  {
    requirement_id: 'r3',
    original: '展示项目。',
    revised: '向课程小组展示数据分析过程。',
    rationale: '说明实际沟通对象和内容。',
    evidence_ids: ['e2'],
    requires_user_input: false,
  },
];

const originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
const renderSuggestions = (selectionKey = 'item-1', values = suggestions) => (
  <ReportSuggestions
    selectionKey={selectionKey}
    suggestions={values}
    renderEvidence={(ids) => <p>引用原文：{ids.join(', ') || '暂无证据'}</p>}
  />
);

function clipboard(writeText = vi.fn().mockResolvedValue(undefined)) {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  return writeText;
}

afterEach(() => {
  if (originalClipboard) Object.defineProperty(navigator, 'clipboard', originalClipboard);
  else Reflect.deleteProperty(navigator, 'clipboard');
});

describe('report modification checklist', () => {
  it('copies only selected ready suggestions in report order and preserves their context', async () => {
    const writeText = clipboard();
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    render(renderSuggestions());
    expect(screen.getAllByRole('checkbox')).toHaveLength(2);
    expect(screen.getByRole('button', { name: '复制建议 2' })).toBeEnabled();
    expect(screen.getByText(/这条建议需要补充真实信息，不能直接作为完成稿/)).toBeInTheDocument();
    expect(screen.getByText(suggestions[0].original!)).toBeInTheDocument();
    expect(screen.getByText(`修改依据：${suggestions[0].rationale}`)).toBeInTheDocument();
    expect(screen.getByText('引用原文：e1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '复制修改清单' })).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox', { name: '加入修改清单：建议 3' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '加入修改清单：建议 1' }));
    const expected = `1. ${suggestions[0].revised}\n\n2. ${suggestions[2].revised}`;
    expect(screen.getByRole('textbox', { name: '本次修改清单内容' })).toHaveValue(expected);
    fireEvent.click(screen.getByRole('button', { name: '复制修改清单' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expected));
    expect(await screen.findByRole('status')).toHaveTextContent('已复制');
    expect(storage).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('checkbox', { name: '加入修改清单：建议 1' }));
    expect(screen.getByRole('textbox', { name: '本次修改清单内容' })).toHaveValue(
      `1. ${suggestions[2].revised}`,
    );
    fireEvent.click(screen.getByRole('button', { name: '清空选择' }));
    expect(screen.queryByRole('textbox', { name: '本次修改清单内容' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '复制修改清单' })).toBeDisabled();
  });

  it('never includes fact templates when selecting all', () => {
    render(renderSuggestions());
    fireEvent.click(screen.getByRole('button', { name: '全选可用建议' }));
    expect(screen.getByRole('heading', { name: '本次修改清单 · 已选 2 条' })).toBeInTheDocument();
    expect(
      (screen.getByRole('textbox', { name: '本次修改清单内容' }) as HTMLTextAreaElement).value,
    ).not.toContain('[项目]');
    expect(screen.getByRole('button', { name: '全选可用建议' })).toBeDisabled();
  });

  it('locks selection while a clipboard write is pending so success matches the current checklist', async () => {
    let finishCopy!: () => void;
    const pendingCopy = new Promise<void>((resolve) => {
      finishCopy = resolve;
    });
    const writeText = clipboard(vi.fn().mockReturnValue(pendingCopy));
    render(renderSuggestions());
    const first = screen.getByRole('checkbox', { name: '加入修改清单：建议 1' });
    const third = screen.getByRole('checkbox', { name: '加入修改清单：建议 3' });
    const selectAll = screen.getByRole('button', { name: '全选可用建议' });
    const clear = screen.getByRole('button', { name: '清空选择' });
    fireEvent.click(first);
    const expected = `1. ${suggestions[0].revised}`;

    fireEvent.click(screen.getByRole('button', { name: '复制修改清单' }));
    expect(writeText).toHaveBeenCalledWith(expected);
    for (const control of [first, third, selectAll, clear]) {
      expect(control).toBeDisabled();
      fireEvent.click(control);
    }
    expect(first).toBeChecked();
    expect(third).not.toBeChecked();
    expect(screen.getByRole('textbox', { name: '本次修改清单内容' })).toHaveValue(expected);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    await act(async () => finishCopy());
    expect(screen.getByRole('status')).toHaveTextContent('已复制');
    expect(screen.getByRole('textbox', { name: '本次修改清单内容' })).toHaveValue(expected);
    for (const control of [first, third, selectAll, clear]) expect(control).toBeEnabled();
    fireEvent.click(third);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '本次修改清单内容' })).toHaveValue(
      `${expected}\n\n2. ${suggestions[2].revised}`,
    );
  });

  it('retains choices on data refresh but resets on item or suggestion changes', () => {
    const { rerender } = render(renderSuggestions());
    fireEvent.click(screen.getByRole('checkbox', { name: '加入修改清单：建议 1' }));
    rerender(renderSuggestions('item-1', structuredClone(suggestions)));
    expect(screen.getByRole('checkbox', { name: '加入修改清单：建议 1' })).toBeChecked();

    rerender(renderSuggestions('item-2'));
    expect(screen.getByRole('checkbox', { name: '加入修改清单：建议 1' })).not.toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: '加入修改清单：建议 1' }));
    const updated = structuredClone(suggestions);
    updated[0].revised = '新的报告建议。';
    rerender(renderSuggestions('item-2', updated));
    expect(screen.getByRole('checkbox', { name: '加入修改清单：建议 1' })).not.toBeChecked();
    expect(screen.getByRole('button', { name: '复制修改清单' })).toBeDisabled();
    rerender(renderSuggestions('item-1'));
    expect(screen.getByRole('checkbox', { name: '加入修改清单：建议 1' })).not.toBeChecked();
  });

  it('keeps the selected text accessible when clipboard permission is denied', async () => {
    clipboard(vi.fn().mockRejectedValue(new Error('permission denied')));
    render(renderSuggestions());
    fireEvent.click(screen.getByRole('button', { name: '全选可用建议' }));
    fireEvent.click(screen.getByRole('button', { name: '复制修改清单' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('无法复制，请手动选取');
    expect(screen.getByRole('textbox', { name: '本次修改清单内容' })).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: '复制修改清单' })).toBeEnabled();
  });

  it('reports unavailable clipboard access for individual suggestions too', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    render(renderSuggestions());
    fireEvent.click(screen.getByRole('button', { name: '复制建议 1' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('无法复制，请手动选取');
  });

  it('explains why no selection is available for a template-only report', () => {
    render(renderSuggestions('only-template', [suggestions[1]]));
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '全选可用建议' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '复制修改清单' })).toBeDisabled();
    expect(screen.getByText('当前建议均需先补充事实，暂不能加入修改清单。')).toBeInTheDocument();
  });
});

it.each([1, 2])('copies user edited suggestion %s including incomplete drafts', async (index) => {
  const write = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: write },
  });
  render(
    <ReportSuggestions
      selectionKey="edited"
      suggestions={suggestions}
      renderEvidence={() => null}
    />,
  );
  fireEvent.change(screen.getByRole('textbox', { name: `编辑建议 ${index}` }), {
    target: { value: '我核对并修改后的经历表达。' },
  });
  fireEvent.click(screen.getByRole('button', { name: `复制建议 ${index}` }));
  await waitFor(() => expect(write).toHaveBeenCalledWith('我核对并修改后的经历表达。'));
});
