import { createRouter, createWebHistory } from 'vue-router';

const routes = [
  { path: '/', redirect: '/datasets' },
  { path: '/datasets', name: '态势感知数据集中心', component: () => import('@/views/Model/DatasetCenter.vue'), meta: { title: '态势感知数据集中心' } },
  { path: '/datasets/:datasetId', name: '数据集详情', component: () => import('@/views/Dataset/DatasetDetailView.vue'), meta: { title: '数据集详情' } },
  { path: '/risk', name: '贝叶斯网络模型训练', component: () => import('@/views/Model/RiskAnalysis.vue'), meta: { title: '贝叶斯网络模型训练' } },
  { path: '/models', name: '贝叶斯网络模型中心', component: () => import('@/views/Model/ModelCenter.vue'), meta: { title: '贝叶斯网络模型中心' } },
  { path: '/:pathMatch(.*)*', redirect: '/datasets' },
];

const router = createRouter({ history: createWebHistory(), routes });
router.afterEach((to) => {
  document.title = `${String(to.meta.title || '基于贝叶斯网络的复杂系统态势感知软件')} - 基于贝叶斯网络的复杂系统态势感知软件`;
});
export default router;
