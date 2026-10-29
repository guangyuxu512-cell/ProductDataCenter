export type FieldWidth = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'full'

export type OverlaySize = 'sm' | 'md' | 'lg'

export type DialogSize = OverlaySize | 'xl' | 'workspace'

export type AppOptionValue = string | number

export type AppSelectValue = AppOptionValue | AppOptionValue[]

export interface AppOption {
  label: string
  value: AppOptionValue
  disabled?: boolean
}
