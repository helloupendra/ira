// A form from a tool's JSON schema: the fields to show, and the typed
// parameters to send once the person has filled them in. Tools get their
// schema from their Python signature, so the shapes here are the ones
// pydantic produces: plain types, enums, "anyOf" with null for optionals,
// and $ref into $defs for enum classes and nested models.

export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: unknown[];
  default?: unknown;
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  allOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  format?: string;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  additionalProperties?: boolean | JsonSchema;
}

export type FieldKind = 'text' | 'number' | 'integer' | 'boolean' | 'select' | 'json';

export interface Field {
  name: string;
  label: string;
  kind: FieldKind;
  required: boolean;
  description?: string;
  options?: string[];
  defaultValue: string;
  placeholder?: string;
}

export type Values = Record<string, string>;

export interface Parsed {
  params: Record<string, unknown>;
  errors: Record<string, string>;
}

// "find_slots" and "patientName" both read as words with a capital.
export function labelFor(name: string): string {
  const words = name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_\s]+/g, ' ')
    .trim()
    .toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : name;
}

function resolve(schema: JsonSchema, root: JsonSchema): JsonSchema {
  if (!schema.$ref) return schema;
  const match = /^#\/\$defs\/([^/]+)$/.exec(schema.$ref);
  const found = match ? root.$defs?.[match[1] ?? ''] : undefined;
  return found ? resolve(found, root) : {};
}

// The schema without its "null" branch, and whether null was allowed.
function unwrapNull(schema: JsonSchema, root: JsonSchema): { inner: JsonSchema; nullable: boolean } {
  const branches = (schema.anyOf ?? []).map((b) => resolve(b, root));
  if (branches.length) {
    const real = branches.filter((b) => b.type !== 'null');
    const nullable = real.length !== branches.length;
    if (real.length === 1) return { inner: real[0] ?? {}, nullable };
    return { inner: { ...schema, anyOf: real }, nullable };
  }
  if (Array.isArray(schema.type)) {
    const types = schema.type.filter((t) => t !== 'null');
    return { inner: { ...schema, type: types.length === 1 ? types[0] : types }, nullable: types.length !== schema.type.length };
  }
  return { inner: schema, nullable: false };
}

function kindOf(schema: JsonSchema): FieldKind {
  if (schema.enum) return 'select';
  const type = Array.isArray(schema.type) ? undefined : schema.type;
  switch (type) {
    case 'integer':
      return 'integer';
    case 'number':
      return 'number';
    case 'boolean':
      return 'boolean';
    case 'string':
      return 'text';
    case 'object':
    case 'array':
      return 'json';
    default:
      return schema.anyOf ? 'json' : 'text';
  }
}

function asText(value: unknown, kind: FieldKind): string {
  if (value === undefined || value === null) return '';
  if (kind === 'json') return JSON.stringify(value);
  return String(value);
}

export function fieldsFor(schema: JsonSchema): Field[] {
  const root = resolve(schema, schema);
  const required = new Set(root.required ?? []);
  return Object.entries(root.properties ?? {}).map(([name, raw]) => {
    const { inner } = unwrapNull(resolve(raw, schema), schema);
    const kind = kindOf(inner);
    const field: Field = {
      name,
      label: raw.title && raw.title !== labelFor(name) && !/^[A-Z][a-z]+$/.test(raw.title) ? raw.title : labelFor(name),
      kind,
      required: required.has(name),
      defaultValue: asText(raw.default ?? inner.default, kind),
    };
    const description = raw.description ?? inner.description;
    if (description) field.description = description;
    if (kind === 'select') field.options = (inner.enum ?? []).map(String);
    if (kind === 'json') field.placeholder = inner.type === 'array' ? '[ ]' : '{ }';
    return field;
  });
}

// Turn what was typed into parameters. Empty optional fields are left out so
// the tool's own defaults apply; a required field left empty is an error.
export function paramsFrom(fields: Field[], values: Values): Parsed {
  const params: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const text = (values[field.name] ?? '').trim();
    if (text === '') {
      if (field.required) errors[field.name] = 'Required';
      continue;
    }
    switch (field.kind) {
      case 'integer': {
        if (!/^-?\d+$/.test(text)) {
          errors[field.name] = 'Must be a whole number';
          break;
        }
        params[field.name] = Number(text);
        break;
      }
      case 'number': {
        const n = Number(text);
        if (!Number.isFinite(n)) {
          errors[field.name] = 'Must be a number';
          break;
        }
        params[field.name] = n;
        break;
      }
      case 'boolean': {
        if (text === 'true' || text === 'yes' || text === 'on' || text === '1') params[field.name] = true;
        else if (text === 'false' || text === 'no' || text === 'off' || text === '0') params[field.name] = false;
        else errors[field.name] = 'Must be true or false';
        break;
      }
      case 'select': {
        if (field.options && !field.options.includes(text)) {
          errors[field.name] = `Must be one of: ${field.options.join(', ')}`;
          break;
        }
        params[field.name] = text;
        break;
      }
      case 'json': {
        try {
          params[field.name] = JSON.parse(text);
        } catch {
          errors[field.name] = 'Must be valid JSON';
        }
        break;
      }
      default:
        params[field.name] = text;
    }
  }
  return { params, errors };
}

export function initialValues(fields: Field[]): Values {
  return Object.fromEntries(fields.map((f) => [f.name, f.defaultValue]));
}
