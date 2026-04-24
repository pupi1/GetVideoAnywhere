<template>
  <section id="workspace" class="workspace">
    <div class="panel input-panel">
      <h2>开始下载</h2>
      <p class="panel-intro">每行一个链接，先解析，再批量下载。</p>
      <div class="quick-tips">
        <span>支持批量粘贴</span>
        <span>支持格式选择</span>
        <span>支持手机访问</span>
      </div>
      <textarea ref="urlTextareaRef" v-model="urlText" placeholder="每行一个视频链接，支持批量粘贴"></textarea>
      <div class="row">
        <input v-model="formatId" placeholder="格式ID（可选，如 best）" />
        <button @click="handleParse">解析</button>
        <button class="primary" :disabled="isSubmitting" @click="handleDownload">
          {{ isSubmitting ? "提交中..." : "创建下载任务" }}
        </button>
      </div>
      <p class="hint">{{ parseHint }}</p>
      <p v-if="actionMessage" class="action-message">{{ actionMessage }}</p>
      <div v-if="parsedVideo" class="parsed-preview">
        <div class="parsed-cover-wrap">
          <img
            v-if="parsedVideo.thumbnail && !thumbnailLoadFailed"
            :src="parsedVideo.thumbnail"
            :alt="parsedVideo.title || '视频封面'"
            class="parsed-cover"
            @error="thumbnailLoadFailed = true"
          />
          <div v-else class="parsed-cover parsed-cover-fallback">暂无封面</div>
        </div>
        <div class="parsed-meta">
          <h3>{{ parsedVideo.title || "未命名视频" }}</h3>
          <p>时长：{{ formatDuration(parsedVideo.duration) }}</p>
          <p>可用格式：{{ parsedVideo.formats?.length || 0 }}</p>
          <p class="parsed-link">{{ parsedVideo.webpage_url }}</p>
        </div>
      </div>
    </div>

    <div class="panel">
      <h2>任务列表</h2>
      <button class="ghost" @click="refreshTasks">刷新进度</button>
      <p class="panel-intro">下载完成后可直接点击“下载文件”获取本地视频。</p>
      <div class="task-list">
        <article class="task-card" v-for="task in tasks" :key="task.id">
          <p class="task-url">{{ task.url }}</p>
          <div class="status-row">
            <span>{{ task.status }}</span>
            <span>{{ Math.round(task.progress || 0) }}%</span>
          </div>
          <div class="progress"><i :style="{ width: `${task.progress || 0}%` }"></i></div>
          <a v-if="task.status === 'completed'" :href="getDownloadLink(task.id)" target="_blank">下载文件</a>
          <p v-if="task.error" class="error">{{ task.error }}</p>
        </article>
        <p v-if="!tasks.length" class="panel-intro">暂无任务，创建下载任务后会自动显示进度。</p>
      </div>
    </div>

    <div id="premium" class="panel premium">
      <h2>AI 总结与翻译</h2>
      <p class="panel-intro">下载后粘贴字幕或文稿，快速生成摘要与翻译版本。</p>
      <div class="premium-note">Pro 功能预览：后续可接入更强模型与多语种批处理。</div>
      <textarea v-model="aiText" placeholder="粘贴字幕或视频文稿文本"></textarea>
      <div class="row">
        <input v-model="targetLang" placeholder="目标语言（zh/en）" />
        <button @click="handleSummarize">生成总结</button>
        <button @click="handleTranslate">翻译字幕</button>
      </div>
      <p class="result">{{ aiResult }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import {
  createBatchDownloads,
  createDownload,
  getDownloadLink,
  listTasks,
  parseVideo,
  summarizeText,
  translateText,
  type DownloadTask,
} from "../api/client";

const urlText = ref("");
const formatId = ref("");
const parseHint = ref("支持主流平台链接，推荐先解析再下载。");
const tasks = ref<DownloadTask[]>([]);
const aiText = ref("");
const targetLang = ref("zh");
const aiResult = ref("");
const urlTextareaRef = ref<HTMLTextAreaElement | null>(null);
const parsedVideo = ref<any | null>(null);
const thumbnailLoadFailed = ref(false);
const isSubmitting = ref(false);
const actionMessage = ref("");
let pollTimer: number | null = null;

function handleHeroSubmit(event: Event) {
  const customEvent = event as CustomEvent<{ url?: string }>;
  const incomingUrl = customEvent.detail?.url?.trim();
  if (!incomingUrl) return;
  if (!urlText.value.trim()) {
    urlText.value = incomingUrl;
  } else if (!urlText.value.includes(incomingUrl)) {
    urlText.value = `${incomingUrl}\n${urlText.value}`;
  }
  window.setTimeout(() => urlTextareaRef.value?.focus(), 50);
}

async function handleParse() {
  const first = urlText.value.split("\n").map((line) => line.trim()).filter(Boolean)[0];
  if (!first) return;
  try {
    const data = await parseVideo(first);
    parsedVideo.value = data;
    thumbnailLoadFailed.value = false;
    parseHint.value = `${data.title || "视频"} · 可用格式 ${data.formats?.length || 0} 个`;
  } catch (error: any) {
    parsedVideo.value = null;
    thumbnailLoadFailed.value = false;
    parseHint.value = error.message || "解析失败";
  }
}

function formatDuration(seconds?: number | null) {
  if (!seconds || Number.isNaN(seconds)) return "未知";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

async function handleDownload() {
  const urls = urlText.value.split("\n").map((line) => line.trim()).filter(Boolean);
  if (!urls.length) return;
  isSubmitting.value = true;
  actionMessage.value = "";
  try {
    if (urls.length === 1) {
      const task = await createDownload(urls[0], formatId.value || undefined);
      tasks.value = [task, ...tasks.value.filter((item) => item.id !== task.id)];
      actionMessage.value = "下载任务已创建，正在后台处理。";
    } else {
      const newTasks = await createBatchDownloads(urls, formatId.value || undefined);
      const existing = new Map(tasks.value.map((task) => [task.id, task]));
      for (const task of newTasks) existing.set(task.id, task);
      tasks.value = Array.from(existing.values());
      actionMessage.value = `批量任务已创建（${newTasks.length}个），正在后台处理。`;
    }
    await refreshTasks();
  } catch (error: any) {
    actionMessage.value = error?.message || "创建下载任务失败，请稍后重试。";
  } finally {
    isSubmitting.value = false;
  }
}

async function refreshTasks() {
  try {
    tasks.value = await listTasks();
  } catch (error: any) {
    actionMessage.value = error?.message || "刷新任务失败";
  }
}

async function handleSummarize() {
  if (!aiText.value.trim()) return;
  const data = await summarizeText(aiText.value);
  aiResult.value = `总结：${data.summary}\n关键词：${data.keywords}`;
}

async function handleTranslate() {
  if (!aiText.value.trim()) return;
  const data = await translateText(aiText.value, targetLang.value || "zh");
  aiResult.value = data.translated_text;
}

onMounted(() => {
  refreshTasks();
  window.addEventListener("hero-url-submit", handleHeroSubmit as EventListener);
  pollTimer = window.setInterval(() => {
    refreshTasks();
  }, 3000);
});

onUnmounted(() => {
  window.removeEventListener("hero-url-submit", handleHeroSubmit as EventListener);
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>
