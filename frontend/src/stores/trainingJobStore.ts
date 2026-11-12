//训练任务的后台轮询 store
//1 秒查一次 model-versions/{id}，到 COMPLETED / FAILED 就弹通知并停表
import { defineStore } from 'pinia';
import { ElNotification } from 'element-plus';
import { getModelVersionDetail } from '@/api/trainingApi';
import { createIsTerminal, messageOf, trimFinishedJobs } from '@/utils/job';
import { createStorePoller } from './jobPollingCore';
import type { PollContext } from './jobPollingCore';
const currentUid = (): string => 'local';
const TRAINING = 'TRAINING';
const COMPLETED = 'COMPLETED';
const FAILED = 'FAILED';
const TERMINAL_STATUSES = [COMPLETED, FAILED];
const POLL_INTERVAL_MS = 1000;
const POLL_TIMEOUT_MS = 65 * 60 * 1000;
//已结束的任务最多留 20 条
const MAX_FINISHED = 20;

export interface BackgroundTrainingJob {
  modelVersionId: number;
  title: string;
  status: string;
  error: string | null;
  startedAt: number;
}

const pollFor = createStorePoller(POLL_INTERVAL_MS, currentUid);
const isTerminal = createIsTerminal<BackgroundTrainingJob>(TERMINAL_STATUSES);
//同一个模型只弹一次通知轮询回包里会连续出现好几次
//去重
const settledByStore = new WeakMap<object, Set<number>>();
const settledIdsFor = (store: object): Set<number> => {
  let ids = settledByStore.get(store);
  if (!ids) {
    ids = new Set<number>();
    settledByStore.set(store, ids);
  }
  return ids;
};

export const useTrainingJobStore = defineStore('trainingJob', {
  state: () => ({ jobs: [] as BackgroundTrainingJob[] }),

  getters: {
    running: (state): boolean => state.jobs.some((job) => !isTerminal(job)),
    //顶栏那个"训练中"按钮显示最近一条，所以取数组末尾
    activeJob: (state): BackgroundTrainingJob | null =>
      state.jobs.filter((job) => !isTerminal(job)).at(-1) ?? null,
    runningJobs: (state): BackgroundTrainingJob[] => state.jobs.filter((job) => !isTerminal(job)),
  },

  actions: {
    track(modelVersionId: number, title: string) {
      //同一个 modelVersionId 只入队一次
      const key = String(modelVersionId);
      if (this.jobs.some((job) => String(job.modelVersionId) === key)) return;
      this.jobs.push({ modelVersionId, title, status: TRAINING, error: null, startedAt: Date.now() });
      this.startPolling();
    },
    startPolling() { pollFor(this).start(); },
    stopPolling() { pollFor(this).stop(); },
    _tick(): Promise<void> { return pollFor(this).tick(); },
    async _poll(context: PollContext) {
      if (!context.isCurrent()) return;
      const running = this.runningJobs;
      if (!running.length) {
        this.stopPolling();
        return;
      }
      for (const job of running) {
        if (!context.isCurrent()) return;
        if (Date.now() - job.startedAt >= POLL_TIMEOUT_MS) {
          this._timeout(job);
          continue;
        }
        try {
          const row = await getModelVersionDetail(job.modelVersionId);
          if (!context.isCurrent()) return;
          job.status = String(row?.status ?? '');
          if (job.status === TRAINING) continue;
          //失败的模型后端会把原因塞在 evaluation_metrics.error 里，没有就留空
          job.error = String(row?.evaluation_metrics?.error ?? '') || null;
          this._settle(job);
        } catch (err) {
          if (!context.isCurrent()) return;
          //查询失败不结束任务，保留上一次的错误信息
          job.error = messageOf(err, job.error ?? '训练状态查询失败');
        }
      }
      if (context.isCurrent() && !this.running) this.stopPolling();
    },
    _settle(job: BackgroundTrainingJob) {
      const settledIds = settledIdsFor(this);
      if (settledIds.has(job.modelVersionId)) return;
      settledIds.add(job.modelVersionId);
      this._trimFinished();
      if (job.status === COMPLETED) {
        ElNotification({
          title: '模型训练完成',
          message: `《${job.title}》已训练完成，可在贝叶斯网络模型中心查看评价或导出`,
          type: 'success',
        });
        return;
      }
      ElNotification({
        title: '模型训练失败',
        message: `《${job.title}》：${job.error || `训练状态 ${job.status}`}`,
        type: 'error',
        duration: 0,
      });
    },
    _trimFinished() {
      this.jobs = trimFinishedJobs(this.jobs, isTerminal, (job) => String(job.modelVersionId), MAX_FINISHED);
    },
    _timeout(job: BackgroundTrainingJob) {
      //超时先把任务从列表摘掉，提示语里让用户去模型中心再看一眼
      this.jobs = this.jobs.filter((item) => item.modelVersionId !== job.modelVersionId);
      ElNotification({
        title: '模型训练仍在进行',
        message: `《${job.title}》等待超时，训练可能仍在后台继续，可稍后在贝叶斯网络模型中心查看`,
        type: 'warning',
        duration: 0,
      });
    },
  },
});
