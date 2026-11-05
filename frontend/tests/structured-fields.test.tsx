import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { AttributeEditor, ConditionEditor } from '../src/components/StructuredFieldsEditor';
import { conditionKey } from '../src/structuredFields';
import { validateJob, validateProfile } from '../src/validation';
import type { Fact, Requirement, JobContent, ProfileContent } from '../src/types';

const fact: Fact = {
  id: 'f1',
  kind: 'credential',
  label: '考试A',
  value: null,
  polarity: 'positive',
  application: 'claimed',
  start_month: null,
  end_month: null,
  completed: null,
  evidence_ids: ['e1'],
  attributes: [{ name: 'credential_status', value: 'partial', quote: '考试A部分通过' }],
};
const requirement: Requirement = {
  id: 'r1',
  quote: '考试A或B部分通过',
  category: 'other',
  importance: 'preferred',
  operator: 'criteria',
  target: '证书',
  subject: null,
  ignored: false,
  ignore_reason: null,
  condition: {
    any_of: [
      {
        scope: 'profile',
        all_of: [{ field: 'credential', comparison: 'any_pass', value: '考试A', quote: '考试A' }],
      },
      {
        scope: 'profile',
        all_of: [{ field: 'credential', comparison: 'any_pass', value: '考试B', quote: 'B' }],
      },
    ],
  },
};

describe('structured evidence editing', () => {
  it('edits certificate progress without discarding source quotes', () => {
    let saved = fact.attributes;
    function Harness() {
      const [value, setValue] = useState(fact);
      return (
        <AttributeEditor
          fact={value}
          onChange={(attrs) => {
            saved = attrs;
            setValue({ ...value, attributes: attrs });
          }}
        />
      );
    }
    render(<Harness />);
    fireEvent.change(screen.getByLabelText('条件值'), { target: { value: 'complete' } });
    expect(saved?.[0]).toEqual({
      name: 'credential_status',
      value: 'complete',
      quote: '考试A部分通过',
    });
  });
  it('keeps two OR alternatives in one requirement and only offers compatible comparisons', () => {
    let saved = requirement.condition!;
    function Harness() {
      const [value, setValue] = useState(saved);
      return (
        <ConditionEditor
          value={value}
          quote={requirement.quote}
          onChange={(v) => {
            saved = v;
            setValue(v);
          }}
        />
      );
    }
    render(<Harness />);
    expect(screen.queryAllByRole('option', { name: '至少' })).toHaveLength(0);
    fireEvent.change(screen.getAllByLabelText('满足方式')[1], { target: { value: 'complete' } });
    expect(saved.any_of).toHaveLength(2);
    expect(saved.any_of[1].all_of[0].comparison).toBe('complete');
    expect(saved.any_of[0].all_of[0].comparison).toBe('any_pass');
  });
  it('validates values, source linkage and equivalent condition ordering', () => {
    const p: ProfileContent = {
      overview: '合成',
      as_of_month: '2026-01',
      facts: [fact],
      evidence: [
        {
          id: 'e1',
          source_id: 'synthetic',
          source_type: 'manual',
          quote: '考试A部分通过',
          locator: null,
        },
      ],
    };
    expect(validateProfile(p)).toEqual({});
    p.facts = [
      {
        ...fact,
        attributes: [{ name: 'credential_status', value: 'invented', quote: '考试A部分通过' }],
      },
    ];
    expect(validateProfile(p)).toHaveProperty('facts.0.evidence_ids');
    const duplicate = structuredClone(requirement);
    duplicate.id = 'r2';
    duplicate.target = '另一个标题';
    duplicate.condition!.any_of.reverse();
    expect(conditionKey(duplicate)).toBe(conditionKey(requirement));
    const j: JobContent = {
      title: '合成',
      company_name: null,
      company_context: '',
      requirements: [requirement, duplicate],
    };
    expect(validateJob(requirement.quote, j)).toHaveProperty('requirements.1');
  });
});
