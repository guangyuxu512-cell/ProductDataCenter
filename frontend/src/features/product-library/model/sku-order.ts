interface SpecGroup {
  values: ReadonlyArray<{ id: string }>
}

/** Sort the view by the current specification order without altering SKU data. */
export function orderSkuRows<T extends { specIds: readonly string[] }>(
  rows: readonly T[], groups: readonly SpecGroup[], imageGroupIndex = 0,
): T[] {
  if (!groups.length) return [...rows]
  const ranks = groups.map((group) => new Map(group.values.map((value, index) => [value.id, index])))
  if (groups.some((group, index) => !group.values.length || ranks[index].size !== group.values.length) ||
      rows.some((row) => row.specIds.length !== groups.length ||
        row.specIds.some((id, index) => !ranks[index].has(id)))) return [...rows]

  const axes = groups.map((_, index) => index)
  if (imageGroupIndex > 0 && imageGroupIndex < axes.length) {
    axes.splice(imageGroupIndex, 1)
    axes.unshift(imageGroupIndex)
  }
  return rows.map((row, index) => ({ row, index })).sort((a, b) => {
    for (const axis of axes) {
      const difference = ranks[axis].get(a.row.specIds[axis])! - ranks[axis].get(b.row.specIds[axis])!
      if (difference) return difference
    }
    return a.index - b.index
  }).map(({ row }) => row)
}

/** Merge only adjacent rows that share the same actual specification ID. */
export function skuGroupRowSpans(rows: ReadonlyArray<{ specIds: readonly string[] }>, axis: number): number[] {
  const spans = rows.map(() => 1)
  if (axis < 0 || rows.some((row) => !row.specIds[axis])) return spans
  for (let start = 0; start < rows.length;) {
    let end = start + 1
    while (end < rows.length && rows[end].specIds[axis] === rows[start].specIds[axis]) end++
    spans[start] = end - start
    start = end
  }
  return spans
}
