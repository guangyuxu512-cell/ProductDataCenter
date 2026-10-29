import platformAllIcon from '../assets/platform-all.svg'
import platformDouyinIcon from '../assets/platform-douyin.svg'
import platformPddIcon from '../assets/platform-pdd.svg'
import platformTaobaoIcon from '../assets/platform-taobao.svg'
import platformWechatChannelsIcon from '../assets/platform-wechat-channels.svg'

export interface PlatformDefinition<Code extends string = string> {
  code: Code
  label: string
  icon: string
  enabled: boolean
  registered: boolean
  capabilities: PlatformCapabilities
}

export type PlatformCapabilityStatus = 'available' | 'planned' | 'unavailable'

export interface PlatformCapabilities {
  legacyShopCreate: PlatformCapabilityStatus
  credentialManagement: PlatformCapabilityStatus
  shopOnboarding: PlatformCapabilityStatus
  authentication: PlatformCapabilityStatus
  sessionCapture: PlatformCapabilityStatus
  dataFetch: PlatformCapabilityStatus
  rpa: PlatformCapabilityStatus
}

/** 前端平台展示的唯一正式来源。Backend 支持能力必须由独立字段诚实表达。 */
export const PLATFORM_REGISTRY = [
  {
    code: 'douyin',
    label: '抖店',
    icon: platformDouyinIcon,
    enabled: true,
    registered: true,
    capabilities: {
      legacyShopCreate: 'available',
      credentialManagement: 'available',
      shopOnboarding: 'available',
      authentication: 'available',
      sessionCapture: 'available',
      dataFetch: 'planned',
      rpa: 'planned',
    },
  },
  {
    code: 'pdd',
    label: '拼多多',
    icon: platformPddIcon,
    enabled: true,
    registered: true,
    capabilities: {
      legacyShopCreate: 'available',
      credentialManagement: 'available',
      shopOnboarding: 'available',
      authentication: 'available',
      sessionCapture: 'available',
      dataFetch: 'planned',
      rpa: 'planned',
    },
  },
  {
    code: 'taobao',
    label: '淘宝',
    icon: platformTaobaoIcon,
    enabled: true,
    registered: true,
    capabilities: {
      legacyShopCreate: 'unavailable',
      credentialManagement: 'unavailable',
      shopOnboarding: 'planned',
      authentication: 'planned',
      sessionCapture: 'planned',
      dataFetch: 'planned',
      rpa: 'planned',
    },
  },
  {
    code: 'wechat_channels',
    label: '视频号',
    icon: platformWechatChannelsIcon,
    enabled: true,
    registered: true,
    capabilities: {
      legacyShopCreate: 'unavailable',
      credentialManagement: 'unavailable',
      shopOnboarding: 'planned',
      authentication: 'planned',
      sessionCapture: 'planned',
      dataFetch: 'planned',
      rpa: 'planned',
    },
  },
] as const satisfies ReadonlyArray<PlatformDefinition>

export type PlatformCode = (typeof PLATFORM_REGISTRY)[number]['code']

export interface PlatformSelectOption {
  [key: string]: unknown
  label: string
  value: PlatformCode
  disabled: boolean
}

export interface PlatformOnboardingOption {
  [key: string]: unknown
  label: string
  value: PlatformCode
  disabled: boolean
}

export const PLATFORM_ALL_NAV_ITEM = {
  code: 'all',
  label: '全部平台',
  icon: platformAllIcon,
} as const

export function getPlatformDefinition<Code extends string>(
  code: Code,
  registry: ReadonlyArray<PlatformDefinition> = PLATFORM_REGISTRY,
): PlatformDefinition<Code> | undefined {
  return registry.find((platform) => platform.code === code) as
    PlatformDefinition<Code> | undefined
}

export function getPlatformNavigationItems(
  registry: ReadonlyArray<PlatformDefinition> = PLATFORM_REGISTRY,
): PlatformDefinition[] {
  return registry.filter((platform) => platform.enabled)
}

export function getPlatformCreateOptions(
  registry: ReadonlyArray<PlatformDefinition> = PLATFORM_REGISTRY,
): PlatformSelectOption[] {
  return registry
    .filter((platform) => platform.enabled)
    .map((platform) => ({
      label: platform.label,
      value: platform.code as PlatformCode,
      disabled: platform.capabilities.legacyShopCreate !== 'available',
    }))
}

export function getPlatformOnboardingOptions(
  registry: ReadonlyArray<PlatformDefinition> = PLATFORM_REGISTRY,
): PlatformOnboardingOption[] {
  return registry
    .filter((platform) => platform.enabled && platform.registered)
    .map((platform) => ({
      label: platform.label,
      value: platform.code as PlatformCode,
      disabled:
        platform.capabilities.shopOnboarding !== 'available' ||
        platform.capabilities.authentication !== 'available' ||
        platform.capabilities.sessionCapture !== 'available',
    }))
}

export const PLATFORM_NAVIGATION_ITEMS = PLATFORM_REGISTRY.filter(
  (platform) => platform.enabled,
)
export const PLATFORM_CREATE_OPTIONS = getPlatformCreateOptions()
export const PLATFORM_ONBOARDING_OPTIONS = getPlatformOnboardingOptions()
