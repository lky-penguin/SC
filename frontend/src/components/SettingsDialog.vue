<template>
  <el-dialog
    v-model="visible" class="settings-dialog" width="560px" top="12vh" append-to-body
    :close-on-click-modal="false" @closed="editorVisible = false"
  >
    <template #header>
      <div class="settings-dialog__heading"><h3>AI 解析与评价</h3></div>
    </template>
    <div class="settings-dialog__content" :aria-busy="loading">
      <div class="config-list" aria-label="当前 AI 配置">
        <div class="config-row">
          <span class="config-row__label">URL</span>
          <span
            class="config-row__value"
            :class="{ 'is-empty': !loading && setting && !setting.base_url }"
          ><template v-if="!loading && setting">{{ setting.base_url || '无' }}</template></span>
        </div>
        <div class="config-row">
          <span class="config-row__label">模型</span>
          <span
            class="config-row__value"
            :class="{ 'is-empty': !loading && setting && !setting.model }"
          ><template v-if="!loading && setting">{{ setting.model || '无' }}</template></span>
        </div>
        <div class="config-row">
          <span class="config-row__label">API key</span>
          <span
            class="config-row__value"
            :class="{ 'is-empty': !loading && setting && !setting.api_key_masked }"
          ><template v-if="!loading && setting">{{ apiKeyDisplay }}</template></span>
        </div>
      </div>
    </div>
    <template #footer>
      <div class="settings-dialog__footer">
        <button
          class="settings-action settings-action--ghost"
          type="button"
          :disabled="loading || testing || !setting?.configured"
          @click="testConnection"
        >
          {{ testing ? '测试中…' : '测试连通性' }}
        </button>
        <button
          class="settings-action settings-action--primary"
          type="button"
          :disabled="loading"
          @click="openEditor"
        >编辑</button>
      </div>
    </template>
  </el-dialog>

  <el-dialog
    v-model="editorVisible"
    class="settings-editor-dialog"
    title="编辑 AI 配置"
    width="500px"
    top="16vh"
    append-to-body
    :close-on-click-modal="false"
  >
    <div class="editor-form">
      <label class="editor-field">
        <span class="editor-field__label">URL</span>
        <input
          v-model="form.base_url"
          class="editor-input"
          type="url"
          placeholder="https://api.openai.com/v1"
          autocomplete="url"
        />
      </label>
      <label class="editor-field">
        <span class="editor-field__label">模型</span>
        <input
          v-model="form.model"
          class="editor-input"
          type="text"
          placeholder="gpt-4o-mini"
          autocomplete="off"
        />
      </label>
      <label class="editor-field">
        <span class="editor-field__label">API key</span>
        <input
          ref="apiKeyInput"
          v-model="form.api_key"
          class="editor-input"
          type="text"
          spellcheck="false"
          :placeholder="setting?.api_key_readable === false ? '请重新输入 API Key' : setting?.api_key_masked ? '当前 key 已脱敏展示' : '请输入 API key'"
          autocomplete="new-password"
          @focus="apiKeyInput?.select()"
        />
      </label>
      <p class="editor-note">编辑框仅展示脱敏后的当前 key。输入新 key 可替换；保持当前内容不会修改已保存的 key。</p>
    </div>
    <template #footer>
      <div class="editor-footer">
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="saving"
          @click="save"
        >{{ saving ? '保存中…' : '保存' }}</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { getAISetting, testAISetting, updateAISetting, type AISetting } from '@/api/aiSettingApi';

const visible = defineModel<boolean>({ default: false });
const setting = ref<AISetting | null>(null);
const loading = ref(false);
const testing = ref(false);
const saving = ref(false);
const editorVisible = ref(false);
const form = ref({ provider: 'openai-compatible', base_url: '', model: '', api_key: '' });
const apiKeyInput = ref<HTMLInputElement | null>(null);

const apiKeyDisplay = computed(() => {
  if (!setting.value) return '';
  if (!setting.value.api_key_masked) return '无';
  if (setting.value.api_key_readable === false) {
    return `${setting.value.api_key_masked}（需重新填写）`;
  }
  return setting.value.api_key_masked;
});

const load = async () => {
  setting.value = null;
  loading.value = true;
  try {
    setting.value = await getAISetting();
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'AI 配置加载失败');
  } finally {
    loading.value = false;
  }
};

watch(visible, (open) => {
  if (!open) {
    editorVisible.value = false;
    return;
  }
  void load();
});

const openEditor = () => {
  form.value = {
    provider: setting.value?.provider || 'openai-compatible',
    base_url: setting.value?.base_url || '',
    model: setting.value?.model || '',
    api_key: setting.value?.api_key_readable === false ? '' : setting.value?.api_key_masked || '',
  };
  editorVisible.value = true;
};

const save = async () => {
  if (!form.value.base_url.trim() || !form.value.model.trim()) {
    ElMessage.warning('请填写 URL 和模型名称');
    return;
  }
  const enteredKey = form.value.api_key.trim();
  const currentMaskedKey = setting.value?.api_key_masked?.trim() || '';
  const nextApiKey = enteredKey && enteredKey !== currentMaskedKey ? enteredKey : undefined;
  if (!nextApiKey && !setting.value?.configured) {
    ElMessage.warning(
      setting.value?.api_key_readable === false
        ? 'API Key 加密信息已失效，请重新填写 API Key'
        : '首次配置需填写 API key',
    );
    return;
  }
  saving.value = true;
  try {
    setting.value = await updateAISetting({
      provider: form.value.provider,
      base_url: form.value.base_url.trim(),
      model: form.value.model.trim(),
      api_key: nextApiKey,
      enabled: true,
    });
    editorVisible.value = false;
    ElMessage.success('AI 配置已保存');
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'AI 配置保存失败');
  } finally {
    saving.value = false;
  }
};

const testConnection = async () => {
  if (!setting.value?.configured) return;
  testing.value = true;
  try {
    const result = await testAISetting();
    result.connected ? ElMessage.success(result.message) : ElMessage.warning(result.message);
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '连接测试失败');
  } finally {
    testing.value = false;
  }
};
</script>

<style scoped>
.settings-dialog__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.settings-dialog__heading h3 {
  margin: 0;
  color: #e8f1ff;
  font-size: 1.08rem;
}

.settings-dialog__content {
  display: grid;
  min-height: 132px;
  gap: 16px;
}

.config-list {
  overflow: hidden;
  border: 1px solid rgba(125,201,255,.12);
  border-radius: 14px;
  background: rgba(5,12,22,.38);
}

.config-row {
  display: grid;
  grid-template-columns: 82px minmax(0,1fr);
  gap: 14px;
  align-items: start;
  padding: 12px 16px;
  border-top: 1px solid rgba(125,201,255,.08);
}

.config-row:first-child { border-top: 0; }

.config-row__label {
  color: rgba(154,214,255,.58);
  font-size: .78rem;
  line-height: 20px;
}

.config-row__value {
  min-width: 0;
  color: #d9e8ff;
  font-size: .84rem;
  line-height: 20px;
  overflow-wrap: anywhere;
  text-align: right;
}

.config-row__value.is-empty { color: rgba(180,200,235,.4); }

.editor-note {
  margin: 0;
  color: rgba(180,200,235,.54);
  font-size: .76rem;
  line-height: 1.7;
}

.settings-dialog__footer,
.editor-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.settings-action {
  height: 36px;
  padding: 0 16px;
  border-radius: 9px;
  font-size: .86rem;
  transition: background .2s,border-color .2s,color .2s,opacity .2s;
}

.settings-action--ghost {
  border: 1px solid rgba(125,201,255,.22);
  background: rgba(8,17,31,.46);
  color: #9ad6ff;
}

.settings-action--ghost:hover:not(:disabled) {
  border-color: rgba(125,201,255,.42);
  background: rgba(91,166,255,.12);
  color: #fff;
}

.settings-action--primary {
  border: 1px solid rgba(125,201,255,.44);
  background: rgba(91,166,255,.18);
  color: #e8f1ff;
  font-weight: 600;
}

.settings-action--primary:hover:not(:disabled) {
  border-color: rgba(125,201,255,.68);
  background: rgba(91,166,255,.27);
}

.settings-action:disabled {
  cursor: not-allowed;
  opacity: .45;
}

.editor-form {
  display: grid;
  gap: 14px;
}

.editor-field {
  display: grid;
  gap: 7px;
}

.editor-field__label {
  color: rgba(220,234,255,.74);
  font-size: .82rem;
}

.editor-input {
  width: 100%;
  padding: 10px 13px;
  border: 1px solid rgba(125,201,255,.2);
  border-radius: 10px;
  outline: none;
  background: rgba(4,10,20,.62);
  color: #e8f1ff;
  font-size: .88rem;
  transition: border-color .2s,box-shadow .2s;
}

.editor-input::placeholder { color: rgba(180,200,235,.34); }

.editor-input:focus {
  border-color: rgba(91,166,255,.58);
  box-shadow: 0 0 0 3px rgba(91,166,255,.1);
}

.editor-footer { gap: 8px; }

@media (max-width: 620px) {
  :global(.settings-dialog),
  :global(.settings-editor-dialog) {
    width: calc(100vw - 32px) !important;
    margin-top: 8vh !important;
  }

  .config-row { grid-template-columns: 70px minmax(0,1fr); }
}
</style>

<style>
.settings-dialog .el-dialog__header,
.settings-editor-dialog .el-dialog__header {
  padding-bottom: 16px;
}

.settings-dialog .el-dialog__body {
  padding-top: 18px;
  padding-bottom: 18px;
}

.settings-dialog .el-dialog__footer,
.settings-editor-dialog .el-dialog__footer {
  padding-top: 13px;
}
</style>
