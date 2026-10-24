// Shared by the OpenStreetMap and Mappls views. Only India is shown: everything outside its official
// boundary is covered in the map's background colour, and the boundary is outlined.
export const MASK_COLOR = '#e2ece7'
export const BORDER_COLOR = '#0e1a2b'

// Reports placed at a town they name (approximate) are grouped into one pin per town, worst evidence first.
export function townGroups(incidents, isShown) {
  const towns = new Map()
  for (const item of incidents) {
    if (!item.approximate_location || item.latitude != null || !isShown(item)) continue
    const { place, latitude, longitude } = item.approximate_location
    if (!towns.has(place)) towns.set(place, { place, latitude, longitude, items: [] })
    towns.get(place).items.push(item)
  }
  return [...towns.values()].map((town) => ({
    ...town,
    tone: town.items.some((item) => item.evidence_status === 'confirmed') ? 'confirmed'
      : town.items.every((item) => item.evidence_status === 'stale') ? 'stale' : 'other',
  }))
}

// A dashed ring with the number of reports: dashed because the town is known, not the exact spot.
export function townPinHtml(town) {
  return `<span class="town-pin ${town.tone}">${town.items.length}</span>`
}

export const townTooltip = (town) => `${town.place} · ${town.items.length} report${town.items.length === 1 ? '' : 's'} name this town (approximate location)`
