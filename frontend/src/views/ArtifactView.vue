<script setup lang="ts">
/** 產物詳情：只呈現後端 metadata；內容以同源附件下載，不在前端解析。 */
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { artifactContentPath, getArtifact, getArtifactContent, type Artifact, type ArtifactStatus } from '../api/artifacts'
import { formatArtifactPreview, supportsArtifactPreview } from '../lib/artifactPreview'
import { describeError } from '../lib/messages'
import { readBackRef } from '../lib/navigationState'
import { client } from '../lib/session'

const route = useRoute()
const artifactId = String(route.params.id ?? '')
const backRef = readBackRef(route.query)

const artifact = ref<Artifact | null>(null)
const error = ref('')
const loading = ref(true)
const preview = ref('')
const previewError = ref('')

const statusLabel: Record<ArtifactStatus, string> = {
  AVAILABLE: '可用',
  QUARANTINED: '已隔離',
  DELETED: '已刪除',
}

const downloadPath = artifactContentPath(artifactId)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  preview.value = ''
  previewError.value = ''
  try {
    artifact.value = await getArtifact(client, artifactId)
    if (supportsArtifactPreview(artifact.value)) {
      try {
        preview.value = formatArtifactPreview(await getArtifactContent<unknown>(client, artifact.value.id))
      } catch (cause) {
        previewError.value = describeError(cause)
      }
    }
  } catch (cause) {
    artifact.value = null
    error.value = describeError(cause)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <h2>產物</h2>
      <div class="actions">
        <RouterLink v-if="backRef !== ''" :to="backRef">
          <button type="button">返回來源頁</button>
        </RouterLink>
        <button type="button" :disabled="loading" @click="load">重新載入</button>
      </div>
    </div>
    <p class="mono id">{{ artifactId }}</p>

    <p v-if="loading" class="muted">載入中…</p>
    <template v-else-if="artifact === null">
      <p class="muted">無法取得此產物的 metadata。</p>
      <p class="muted">
        後端只對存取等級 PROJECT 的產物提供 metadata 與內容；其他等級（如 SEALED_DETAIL）一律以 404 回應，
        不因持有 UUID 而放行。
      </p>
    </template>
    <template v-else>
      <dl class="facts">
        <dt>狀態</dt>
        <dd>{{ statusLabel[artifact.status] }}（{{ artifact.status }}）</dd>
        <dt>媒體類型</dt>
        <dd class="mono">{{ artifact.media_type }}</dd>
        <dt>大小</dt>
        <dd class="mono">{{ artifact.size_bytes }} bytes</dd>
        <dt>存取等級</dt>
        <dd>{{ artifact.access_class }}</dd>
        <dt>位置</dt>
        <dd class="mono">{{ artifact.artifact_uri }}</dd>
        <dt>SHA-256</dt>
        <dd class="mono">{{ artifact.sha256 }}</dd>
        <dt>建立時間</dt>
        <dd class="mono">{{ artifact.created_at }}</dd>
      </dl>

      <h3>內容</h3>
      <p class="muted">
        由後端在回傳前重新校驗雜湊與大小；狀態不是「可用」時會回 409，不以快取內容替代。
      </p>
      <a :href="downloadPath" download>下載 JSON 內容</a>

      <template v-if="supportsArtifactPreview(artifact)">
        <h3>預覽</h3>
        <p v-if="previewError !== ''" class="muted">{{ previewError }}</p>
        <p v-else-if="preview === ''" class="muted">此產物尚未取得可預覽內容。</p>
        <pre v-else class="preview"><code>{{ preview }}</code></pre>
      </template>
    </template>
  </section>

  <p v-if="error" class="alert" role="alert">{{ error }}</p>
</template>

<style scoped>
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.75rem;
  padding: 1.25rem;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
.actions {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}
h2 {
  margin: 0;
  font-size: 1.15rem;
}
h3 {
  margin: 1.25rem 0 0.5rem;
  font-size: 1rem;
}
.id {
  color: var(--text-muted);
  word-break: break-all;
}
.facts {
  display: grid;
  grid-template-columns: minmax(8rem, auto) 1fr;
  gap: 0.35rem 1rem;
  margin: 0.75rem 0 0;
}
.facts dt {
  color: var(--text-muted);
  font-size: 0.9rem;
}
.facts dd {
  margin: 0;
  word-break: break-all;
}
.muted {
  color: var(--text-muted);
  font-size: 0.9rem;
}
.preview {
  margin: 0.75rem 0 0;
  padding: 0.9rem;
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  background: var(--surface-2);
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.alert {
  padding: 0.6rem 0.75rem;
  border-radius: 0.4rem;
  background: var(--danger-surface);
  color: var(--danger);
}
</style>
