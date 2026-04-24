<template>
  <main class="app-shell">
    <header class="top-nav">
      <div class="brand">
        <span class="brand-logo">VD</span>
        <span>VideoAnywhere</span>
      </div>
      <nav>
        <a href="#features">能力</a>
        <a href="#workspace">工作台</a>
        <a href="#premium">高级功能</a>
      </nav>
      <button class="nav-cta">立即试用</button>
    </header>
    <Home />
    <Workspace />
  </main>
</template>

<script setup lang="ts">
import Home from "./pages/Home.vue";
import Workspace from "./pages/Workspace.vue";
</script>
