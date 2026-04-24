<template>
  <div class="page">
    <HeroSection />
    <section id="features" class="value-grid">
      <article class="card card-accent">
        <h3>01 一键解析</h3>
        <p>自动识别标题、时长、可下载清晰度，不用研究平台规则。</p>
      </article>
      <article class="card">
        <h3>02 批量下载</h3>
        <p>一次粘贴多条链接，后台队列执行，省去重复操作。</p>
      </article>
      <article class="card">
        <h3>03 AI增强</h3>
        <p>下载后可做视频总结与字幕翻译，适合学习和二次整理。</p>
      </article>
    </section>

    <section class="masonry-section">
      <div class="section-head">
        <h2>热门下载场景模板</h2>
        <p>像参考站一样用“卡片+标签”表达价值，但聚焦视频下载业务。</p>
      </div>
      <div class="masonry-grid">
        <article class="masonry-card tall">
          <div class="thumb thumb-video"></div>
          <h3>课程视频归档</h3>
          <p># 学习备份 # 离线观看 # 批量下载</p>
        </article>
        <article class="masonry-card">
          <div class="thumb thumb-social"></div>
          <h3>短视频素材收集</h3>
          <p># 创作素材 # 多平台 # 快速筛选</p>
        </article>
        <article class="masonry-card">
          <div class="thumb thumb-mobile"></div>
          <h3>手机端随时保存</h3>
          <p># 移动优先 # 一键下载 # 轻操作</p>
        </article>
        <article class="masonry-card tall">
          <div class="thumb thumb-ai"></div>
          <h3>AI 总结与翻译联动</h3>
          <p># 视频复盘 # 字幕翻译 # 知识提炼</p>
        </article>
        <article class="masonry-card wide">
          <div class="thumb thumb-premium"></div>
          <h3>会员权益预览</h3>
          <p># 更高并发 # 更快速度 # 高级模型</p>
        </article>
      </div>
    </section>

    <section class="pricing-teaser">
      <div>
        <h2>把“下载工具”升级成“效率产品”</h2>
        <p>免费版可用，专业版可解锁更高并发与 AI 增强能力。</p>
      </div>
      <div class="pricing-actions">
        <button class="primary">免费开始</button>
        <button>查看专业版</button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import HeroSection from "../components/HeroSection.vue";
</script>
