<template>
  <section class="hero">
    <p class="badge">跨平台视频下载引擎</p>
    <h1>万能视频下载站，<span>一键保存到本地</span></h1>
    <p class="subtitle">
      支持批量链接、高清格式、移动端可用。把下载这件事，变成输入链接这么简单。
    </p>
    <form class="hero-search" @submit.prevent="submitFromHero">
      <input
        v-model="heroUrl"
        class="hero-search-input"
        type="text"
        placeholder="粘贴视频链接开始下载"
      />
      <button type="submit">立即解析</button>
    </form>
  </section>
</template>

<script setup lang="ts">
import { ref } from "vue";

const heroUrl = ref("");

function submitFromHero() {
  const url = heroUrl.value.trim();
  if (!url) return;
  window.dispatchEvent(new CustomEvent("hero-url-submit", { detail: { url } }));
  document.getElementById("workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
</script>
