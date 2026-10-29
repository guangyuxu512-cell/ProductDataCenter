<script setup lang="ts">
import { APP_OVERLAY_HOST_ID } from './overlay-host'
</script>

<template>
  <div :id="APP_OVERLAY_HOST_ID" class="app-overlay-host" />
</template>

<style>
.app-overlay-host {
  position: absolute;
  z-index: 1;
  top: var(--layout-topbar-height);
  right: 0;
  bottom: 0;
  left: 0;
  overflow: hidden;
  pointer-events: none;
  transform: translateZ(0);
}

.app-overlay-host .n-modal-mask,
.app-overlay-host .n-modal-body-wrapper {
  pointer-events: auto;
}
</style>
