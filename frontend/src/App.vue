<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import SettingsDialog from '@/components/SettingsDialog.vue';

const route = useRoute();
const router = useRouter();
const settingsVisible = ref(false);
const navItems = [
  { path: '/datasets', label: '数据集中心' },
  { path: '/risk', label: 'AI模型训练' },
  { path: '/models', label: '模型中心' },
];
const activePath = computed(() => navItems.find((item) => route.path.startsWith(item.path))?.path ?? route.path);
</script>

<template>
  <div class="app-shell">
    <div class="app-shell__backdrop"></div>
    <header class="topbar">
      <h1 class="topbar__title">风险数据集迭代与贝叶斯模型训练评估系统</h1>
      <div class="topbar__actions">
        <nav class="nav-tabs" aria-label="业务导航">
          <button
            v-for="item in navItems"
            :key="item.path"
            class="nav-tabs__item"
            :class="{ 'is-active': activePath === item.path }"
            @click="router.push(item.path)"
          >{{ item.label }}</button>
        </nav>
        <div class="topbar-right">
          <button
            class="topbar-settings"
            type="button"
            aria-label="设置"
            title="设置"
            :class="{ 'is-active': settingsVisible }"
            :aria-expanded="settingsVisible"
            @click="settingsVisible = true"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3.25" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.37a1.7 1.7 0 0 0-1 .63 1.7 1.7 0 0 0-.36 1.05V21h-4v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.23 15a1.7 1.7 0 0 0-.63-1 1.7 1.7 0 0 0-1.05-.36H2v-4h.09A1.7 1.7 0 0 0 3.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 8 4.23a1.7 1.7 0 0 0 1-.63 1.7 1.7 0 0 0 .36-1.05V2h4v.09A1.7 1.7 0 0 0 14.4 3.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 18.77 8c.08.4.3.76.63 1 .3.23.67.36 1.05.36H21v4h-.09A1.7 1.7 0 0 0 19.4 15Z" />
            </svg>
          </button>
        </div>
      </div>
    </header>
    <main class="new-page-wrap"><router-view /></main>
    <SettingsDialog v-model="settingsVisible" />
  </div>
</template>

<style scoped>
.new-page-wrap {
  padding: 20px 16px;
  min-height: auto;
  box-sizing: border-box;
}

.topbar {
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.topbar__title {
  margin: 0;
  color: #dcecff;
  font-size: clamp(1.45rem, 2.35vw, 2.25rem);
  font-weight: 600;
  line-height: 1.25;
  letter-spacing: .08em;
  text-align: center;
  text-shadow: 0 0 28px rgba(91,166,255,.24);
}

.topbar__actions {
  display: grid;
  grid-template-columns: minmax(0,1fr) auto minmax(0,1fr);
  align-items: center;
  gap: 14px;
}

.topbar__actions .nav-tabs {
  grid-column: 2;
  grid-row: 1;
  justify-self: center;
}

.topbar-right {
  grid-column: 3;
  grid-row: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-shrink: 0;
}

.topbar-settings {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: 1px solid rgba(125,201,255,.18);
  background: rgba(8,17,31,.7);
  color: rgba(154,214,255,.5);
  transition: color .2s,border-color .2s,box-shadow .2s;
}

.topbar-settings svg {
  width: 19px;
  height: 19px;
}

.topbar-settings:hover,
.topbar-settings.is-active {
  color: #7dc9ff;
  border-color: rgba(125,201,255,.45);
  box-shadow: 0 0 0 3px rgba(91,166,255,.14);
}

@media (max-width: 720px) {
  .topbar__actions { grid-template-columns: minmax(0,1fr) auto; }

  .topbar__actions .nav-tabs {
    grid-column: 1;
    justify-self: stretch;
    max-width: 100%;
  }

  .topbar-right { grid-column: 2; }
}
</style>
