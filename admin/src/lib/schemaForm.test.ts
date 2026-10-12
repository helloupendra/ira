import { describe, expect, it } from 'vitest';
import { fieldsFor, initialValues, labelFor, paramsFrom, type JsonSchema } from './schemaForm';

const clinicLike: JsonSchema = {
  type: 'object',
  properties: {
    date: { type: 'string', title: 'Date', description: "YYYY-MM-DD, 'today' or 'tomorrow'" },
    count: { type: 'integer', title: 'Count', default: 3 },
    price: { type: 'number', title: 'Price' },
    urgent: { type: 'boolean', title: 'Urgent', default: false },
    note: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null, title: 'Note' },
    kind: { $ref: '#/$defs/Kind' },
    extras: { type: 'object', title: 'Extras' },
    tags: { type: 'array', items: { type: 'string' }, title: 'Tags' },
    patientName: { type: 'string' },
  },
  required: ['date', 'kind'],
  additionalProperties: false,
  $defs: { Kind: { enum: ['check-up', 'cleaning'], type: 'string', title: 'Kind' } },
};

describe('labelFor', () => {
  it('turns names into words', () => {
    expect(labelFor('find_slots')).toBe('Find slots');
    expect(labelFor('patientName')).toBe('Patient name');
    expect(labelFor('id')).toBe('Id');
  });
});

describe('fieldsFor', () => {
  const fields = fieldsFor(clinicLike);
  const by = Object.fromEntries(fields.map((f) => [f.name, f]));

  it('keeps the schema order and marks required fields', () => {
    expect(fields.map((f) => f.name)).toEqual([
      'date', 'count', 'price', 'urgent', 'note', 'kind', 'extras', 'tags', 'patientName',
    ]);
    expect(by.date?.required).toBe(true);
    expect(by.count?.required).toBe(false);
  });

  it('picks a kind per type, including anyOf-null and $ref enums', () => {
    expect(by.date?.kind).toBe('text');
    expect(by.count?.kind).toBe('integer');
    expect(by.price?.kind).toBe('number');
    expect(by.urgent?.kind).toBe('boolean');
    expect(by.note?.kind).toBe('text');
    expect(by.kind?.kind).toBe('select');
    expect(by.kind?.options).toEqual(['check-up', 'cleaning']);
    expect(by.extras?.kind).toBe('json');
    expect(by.tags?.kind).toBe('json');
  });

  it('carries descriptions, defaults and labels', () => {
    expect(by.date?.description).toBe("YYYY-MM-DD, 'today' or 'tomorrow'");
    expect(by.count?.defaultValue).toBe('3');
    expect(by.urgent?.defaultValue).toBe('false');
    expect(by.note?.defaultValue).toBe('');
    expect(by.patientName?.label).toBe('Patient name');
    expect(initialValues(fields).count).toBe('3');
  });
});

describe('paramsFrom', () => {
  const fields = fieldsFor(clinicLike);

  it('coerces each kind and leaves empty optionals out', () => {
    const { params, errors } = paramsFrom(fields, {
      date: 'tomorrow',
      count: '4',
      price: '12.5',
      urgent: 'true',
      note: '',
      kind: 'cleaning',
      extras: '{"room": 2}',
      tags: '["a","b"]',
      patientName: ' Avery ',
    });
    expect(errors).toEqual({});
    expect(params).toEqual({
      date: 'tomorrow',
      count: 4,
      price: 12.5,
      urgent: true,
      kind: 'cleaning',
      extras: { room: 2 },
      tags: ['a', 'b'],
      patientName: 'Avery',
    });
  });

  it('reports what is wrong, field by field', () => {
    const { params, errors } = paramsFrom(fields, {
      date: '',
      count: '4.5',
      price: 'abc',
      urgent: 'maybe',
      kind: 'surgery',
      extras: '{not json',
      tags: '',
    });
    expect(errors).toEqual({
      date: 'Required',
      count: 'Must be a whole number',
      price: 'Must be a number',
      urgent: 'Must be true or false',
      kind: 'Must be one of: check-up, cleaning',
      extras: 'Must be valid JSON',
    });
    expect(params).toEqual({});
  });

  it('copes with a schema that has no properties', () => {
    expect(fieldsFor({ type: 'object' })).toEqual([]);
    expect(paramsFrom([], {})).toEqual({ params: {}, errors: {} });
  });
});
