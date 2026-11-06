import type { Fact, Requirement } from './types';
export type Criterion = NonNullable<Requirement['condition']>['any_of'][number]['all_of'][number];
export const attributeKinds: Record<string, Fact['kind'][]> = {
  institution: ['education'],
  major: ['education'],
  graduation_year: ['education'],
  enrollment: ['education'],
  experience_type: ['experience'],
  experience_domain: ['experience', 'project'],
  credential_status: ['credential'],
  credential_level: ['credential'],
  availability_days: ['availability'],
  availability_months: ['availability'],
  availability_start: ['availability'],
  full_time: ['availability'],
};
const bounds: Record<string, [number, number]> = {
  graduation_year: [1900, 2200],
  availability_days: [0, 7],
  availability_months: [0, 600],
};
const enums: Record<string, string[]> = {
  enrollment: ['enrolled', 'completed'],
  experience_type: ['internship', 'employment', 'volunteer'],
  credential_status: ['partial', 'complete', 'preparing', 'expired'],
  full_time: ['true', 'false'],
};
export function validStructuredValue(field: string, value: string): boolean {
  if (bounds[field])
    return /^[0-9]{1,4}$/.test(value) && +value >= bounds[field][0] && +value <= bounds[field][1];
  if (enums[field]) return enums[field].includes(value);
  if (field === 'availability_start')
    return value === 'immediate' || /^[0-9]{4}-(0[1-9]|1[0-2])$/.test(value);
  return Boolean(value.trim()) && value.length <= 200;
}
export function comparisonOptions(field: string): Criterion['comparison'][] {
  if (field === 'credential') return ['any_pass', 'complete'];
  if (field === 'skill' || field === 'manual') return ['eq'];
  return bounds[field] || field === 'availability_start'
    ? ['eq', 'exists', 'gte', 'lte']
    : ['eq', 'exists'];
}
export function conditionKey(r: Requirement): string {
  const norm = (v: string) => v.trim().toLowerCase().replace(/\s+/g, ' ');
  return r.condition
    ? JSON.stringify(
        [
          ...new Set(
            r.condition.any_of.map((g) =>
              JSON.stringify([
                g.scope,
                [
                  ...new Set(
                    g.all_of.map((c) => JSON.stringify([c.field, c.comparison, norm(c.value)])),
                  ),
                ].sort(),
              ]),
            ),
          ),
        ].sort(),
      )
    : norm(r.target);
}
export function conditionKinds(field: string): Fact['kind'][] {
  return (
    attributeKinds[field] ??
    (field === 'credential'
      ? ['credential']
      : field === 'skill'
        ? ['skill', 'experience', 'project']
        : [])
  );
}
