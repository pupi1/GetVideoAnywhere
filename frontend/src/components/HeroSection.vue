<template>
  <section class="hero">
    <p class="badge">跨平台视频下载引擎</p>
    <h1>万能视频下载站，<span>一键保存到本地</span></h1>
    <p class="subtitle">
      支持批量链接、高清格式、移动端可用。把下载这件事，变成输入链接这么简单。
    </p>
    <form class="hero-parse-box" @submit.prevent="handleParse">
      <textarea
        v-model="heroUrlText"
        class="hero-parse-textarea"
        placeholder="每行一个视频链接，支持批量粘贴"
      ></textarea>
      <button type="submit" :disabled="isParsing">{{ isParsing ? "解析中..." : "立即解析" }}</button>
    </form>
    <p v-if="heroMessage" class="hero-message">{{ heroMessage }}</p>

    <div v-if="parsedList.length" class="hero-preview-stage">
      <div class="hero-carousel-head">
        <button v-if="parsedList.length > 1" class="ghost" @click="prevItem">上一条</button>
        <p>{{ currentIndex + 1 }} / {{ parsedList.length }}</p>
        <button v-if="parsedList.length > 1" class="ghost" @click="nextItem">下一条</button>
      </div>

      <div class="parsed-preview hero-preview">
        <div class="parsed-cover-wrap">
          <img
            v-if="currentItem.thumbnail && !thumbnailLoadFailed"
            :src="currentItem.thumbnail"
            :alt="currentItem.title || '视频封面'"
            class="parsed-cover hero-cover-large"
            @error="thumbnailLoadFailed = true"
          />
          <div v-else class="parsed-cover parsed-cover-fallback hero-cover-large">暂无封面</div>
        </div>
        <div class="parsed-meta">
          <h3>{{ currentItem.title || "未命名视频" }}</h3>
          <p>时长：{{ formatDuration(currentItem.duration) }}</p>
          <p>可用格式：{{ currentItem.formats?.length || 0 }}</p>
          <p class="parsed-link">{{ currentItem.webpage_url }}</p>
        </div>
      </div>

      <div class="hero-actions">
        <label class="format-label">
          选择分辨率与格式
          <select v-model="selectedFormatId">
            <option value="">自动最佳（best）</option>
            <option v-for="fmt in currentItem.formats || []" :key="fmt.format_id" :value="fmt.format_id">
              {{ fmt.resolution || "unknown" }} · {{ fmt.ext || "auto" }} · {{ fmt.format_id }}
            </option>
          </select>
        </label>
        <button class="primary" @click="startBrowserDownload">
          {{ parsedList.length > 1 ? "下载当前轮播视频" : "浏览器直接下载" }}
        </button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { getBrowserDownloadLink, getDirectBrowserDownloadLink, parseVideo } from "../api/client";

const heroUrlText = ref("https://www.douyin.com/jingxuan?modal_id=7631491472801692603");
const parsedList = ref<any[]>([]);
const sourceUrls = ref<string[]>([]);
const currentIndex = ref(0);
const thumbnailLoadFailed = ref(false);
const heroMessage = ref("");
const selectedFormatId = ref("");
const isParsing = ref(false);

const currentItem = computed(() => parsedList.value[currentIndex.value] || {});

function formatDuration(seconds?: number | null) {
  if (!seconds || Number.isNaN(seconds)) return "未知";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function prevItem() {
  currentIndex.value = (currentIndex.value - 1 + parsedList.value.length) % parsedList.value.length;
  thumbnailLoadFailed.value = false;
  selectedFormatId.value = "";
}

function nextItem() {
  currentIndex.value = (currentIndex.value + 1) % parsedList.value.length;
  thumbnailLoadFailed.value = false;
  selectedFormatId.value = "";
}

async function handleParse() {
  const urls = heroUrlText.value.split("\n").map((line) => line.trim()).filter(Boolean);
  if (!urls.length) return;
  isParsing.value = true;
  try {
    heroMessage.value = `正在解析 ${urls.length} 条链接...`;
    const parsed = await Promise.all(urls.map((url) => parseVideo(url)));
    parsedList.value = parsed;
    sourceUrls.value = urls;
    currentIndex.value = 0;
    thumbnailLoadFailed.value = false;
    selectedFormatId.value = "";
    heroMessage.value = "";
  } catch (error: any) {
    parsedList.value = [];
    thumbnailLoadFailed.value = false;
    heroMessage.value = error?.message || "解析失败，请稍后重试。";
  } finally {
    isParsing.value = false;
  }
}

function startBrowserDownload() {
  if (!sourceUrls.value.length) return;
  const url = sourceUrls.value[currentIndex.value] || sourceUrls.value[0];
  if (!url) return;
  const item = currentItem.value || {};
  const downloadUrl = item.play_url
    ? getDirectBrowserDownloadLink(item.play_url, item.title || "video", "mp4")
    : getBrowserDownloadLink(url, selectedFormatId.value || undefined);
  window.open(downloadUrl, "_blank");
  heroMessage.value = "已触发浏览器下载，请在浏览器下载列表查看进度。";
}
</script>
