import { createRouter, createWebHistory } from 'vue-router';

const routes = [
  { path: '/', redirect: '/datasets' },
  { path: '/datasets', name: '数据集中心', component: () => import('@/views/Model/DatasetCenter.vue'), meta: { title: '数据集中心' } },
  { path: '/datasets/:datasetId', name: '数据集详情', component: () => import('@/views/Dataset/DatasetDetailView.vue'), meta: { title: '数据集详情' } },
  { path: '/risk', name: 'AI模型训练', component: () => import('@/views/Model/RiskAnalysis.vue'), meta: { title: 'AI模型训练' } },
  { path: '/models', name: '模型中心', component: () => import('@/views/Model/ModelCenter.vue'), meta: { title: '模型中心' } },
  { path: '/:pathMatch(.*)*', redirect: '/datasets' },
];

const router = createRouter({ history: createWebHistory(), routes });
router.afterEach((to) => {
  document.title = `${String(to.meta.title || '风险数据集迭代与贝叶斯模型训练评估系统')} - 风险数据集迭代与贝叶斯模型训练评估系统`;
});
export default router;
