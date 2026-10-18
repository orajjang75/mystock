import openapi from '../../../openapi.json'

// The settings form is built from the backend's own schema, so a field added to the Python
// params model shows up here (and a test insists it gets a Korean label).

interface JsonSchema {
  $ref?: string
  type?: string
  enum?: string[]
  default?: unknown
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  properties?: Record<string, JsonSchema>
}

const schemas = openapi.components.schemas as unknown as Record<string, JsonSchema>

export interface Leaf {
  group: string
  field: string
  key: string // "group.field"
  kind: 'integer' | 'number' | 'boolean' | 'enum'
  options: string[]
  min?: number
  max?: number
  exclusiveMin?: number
  exclusiveMax?: number
  default: unknown
}

function resolve(schema: JsonSchema): JsonSchema {
  if (!schema.$ref) return schema
  const name = schema.$ref.split('/').pop() as string
  return schemas[name]
}

function kindOf(schema: JsonSchema): Leaf['kind'] {
  if (schema.enum) return 'enum'
  if (schema.type === 'boolean') return 'boolean'
  return schema.type === 'integer' ? 'integer' : 'number'
}

/** Every editable field of ``SignalParams``. The exported schema sorts keys alphabetically, so
 * the display order comes from the label table instead (see ``orderedLeaves``). */
export function signalParamLeaves(): Leaf[] {
  const groups = schemas.SignalParams.properties ?? {}
  return Object.entries(groups).flatMap(([group, ref]) =>
    Object.entries(resolve(ref).properties ?? {}).map(([field, schema]) => ({
      group,
      field,
      key: `${group}.${field}`,
      kind: kindOf(schema),
      options: schema.enum ?? [],
      min: schema.minimum,
      max: schema.maximum,
      exclusiveMin: schema.exclusiveMinimum,
      exclusiveMax: schema.exclusiveMaximum,
      default: schema.default,
    })),
  )
}

export function signalParamGroups(): string[] {
  return Object.keys(schemas.SignalParams.properties ?? {})
}

/** The defaults the backend declares, shaped like ``SignalParams``. */
export function defaultSignalParams(): Record<string, Record<string, unknown>> {
  const result: Record<string, Record<string, unknown>> = {}
  for (const leaf of signalParamLeaves()) {
    result[leaf.group] = { ...result[leaf.group], [leaf.field]: leaf.default }
  }
  return result
}
