import type { GlobalThemeOverrides } from 'naive-ui'

/** Opt-in list density. Existing controls, pages and overlays keep their defaults. */
export type ListDensity = 'default' | 'compact'

// Sizes only: NConfigProvider immutably merges these into the current parent
// theme. Named tokens are global so a teleported menu retains its size; colors,
// locale, font family and radii continue to come from the active application theme.
const compactListThemeOverrides = {
  Button: {
    heightSmall: 'var(--list-compact-control-height)',
    heightMedium: 'var(--list-compact-control-height)',
    fontSizeSmall: 'var(--list-compact-font-size)',
    fontSizeMedium: 'var(--list-compact-font-size)',
  },
  Input: {
    heightSmall: 'var(--list-compact-control-height)',
    heightMedium: 'var(--list-compact-control-height)',
    fontSizeSmall: 'var(--list-compact-font-size)',
    fontSizeMedium: 'var(--list-compact-font-size)',
  },
  Radio: {
    buttonHeightSmall: 'var(--list-compact-control-height)',
    buttonHeightMedium: 'var(--list-compact-control-height)',
    fontSizeSmall: 'var(--list-compact-font-size)',
    fontSizeMedium: 'var(--list-compact-font-size)',
  },
  Select: {
    peers: {
      InternalSelection: {
        heightSmall: 'var(--list-compact-control-height)',
        heightMedium: 'var(--list-compact-control-height)',
        fontSizeSmall: 'var(--list-compact-font-size)',
        fontSizeMedium: 'var(--list-compact-font-size)',
      },
      InternalSelectMenu: {
        optionFontSizeSmall: 'var(--list-compact-font-size)',
        optionFontSizeMedium: 'var(--list-compact-font-size)',
      },
    },
  },
  DataTable: {
    fontSizeSmall: 'var(--list-compact-font-size)',
    fontSizeMedium: 'var(--list-compact-font-size)',
    thPaddingMedium: 'var(--space-2) var(--space-3)',
    tdPaddingMedium: 'var(--space-2) var(--space-3)',
  },
  Pagination: {
    itemSizeMedium: 'var(--list-compact-control-height)',
    itemFontSizeMedium: 'var(--list-compact-font-size)',
    jumperFontSizeMedium: 'var(--list-compact-font-size)',
  },
  Dropdown: {
    optionHeightSmall: 'var(--list-compact-control-height)',
    optionHeightMedium: 'var(--list-compact-control-height)',
    fontSizeSmall: 'var(--list-compact-font-size)',
    fontSizeMedium: 'var(--list-compact-font-size)',
  },
  Tooltip: { fontSize: 'var(--list-compact-font-size)' },
  Tag: { fontSizeSmall: 'var(--list-compact-font-size)' },
} satisfies GlobalThemeOverrides

export function createListDensityTheme(
  density: ListDensity,
): GlobalThemeOverrides | undefined {
  if (density !== 'compact') return undefined
  // Naive's virtual SelectMenu uses depx(optionHeight) to size its item window.
  // CSS var() works for painting but would become NaN there, hiding all options.
  // Resolve this one numeric dependency from the same authoritative token.
  const height = getComputedStyle(document.documentElement)
    .getPropertyValue('--list-compact-control-height')
    .trim()
  if (!/^\d+(?:\.\d+)?px$/.test(height) || Number.parseFloat(height) <= 0)
    throw new Error('Missing pixel token: --list-compact-control-height')
  return {
    ...compactListThemeOverrides,
    Select: {
      ...compactListThemeOverrides.Select,
      peers: {
        ...compactListThemeOverrides.Select.peers,
        InternalSelectMenu: {
          ...compactListThemeOverrides.Select.peers.InternalSelectMenu,
          optionHeightSmall: height,
          optionHeightMedium: height,
        },
      },
    },
  }
}
