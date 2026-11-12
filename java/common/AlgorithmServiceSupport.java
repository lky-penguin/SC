package com.security.bayes.service;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.json.JSONArray;
import org.json.JSONObject;
import weka.classifiers.AbstractClassifier;
import weka.classifiers.Classifier;
import weka.core.Attribute;
import weka.core.DenseInstance;
import weka.core.Instance;
import weka.core.Instances;
import weka.core.SerializationHelper;
import weka.core.converters.ConverterUtils.DataSource;
import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.Executors;
import java.util.function.Function;
public final class AlgorithmServiceSupport {
    @FunctionalInterface
    public interface ClassifierFactory {
        Classifier create(JSONObject parameters, String algorithmCode) throws Exception;
    }

    @FunctionalInterface
    public interface ExplanationBuilder {
        JSONObject build(Classifier classifier, Instance instance, Instances header,
                JSONArray riskLabels, double[] distribution, String algorithmCode);
    }

    private final ModelCache modelCache;
    private final String serviceName;
    private final String shutdownThreadName;
    private final String[] supportedAlgorithms;
    private final Function<JSONObject, String> algorithmResolver;
    private final ClassifierFactory classifierFactory;
    private final ExplanationBuilder explanationBuilder;

    public AlgorithmServiceSupport(String serviceName, String cacheBudgetProperty, String shutdownThreadName,
            String[] supportedAlgorithms, Function<JSONObject, String> algorithmResolver,
            ClassifierFactory classifierFactory, ExplanationBuilder explanationBuilder) {
        this.modelCache = new ModelCache(cacheBudgetProperty, serviceName);
        this.serviceName = serviceName;
        this.shutdownThreadName = shutdownThreadName;
        this.supportedAlgorithms = supportedAlgorithms.clone();
        this.algorithmResolver = algorithmResolver;
        this.classifierFactory = classifierFactory;
        this.explanationBuilder = explanationBuilder;
    }

    public void start(int port, String healthAlgorithm, String listeningAlgorithm) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        server.createContext("/health", exchange -> handleHealth(exchange, healthAlgorithm));
        server.createContext("/train", this::handleTrain);
        server.createContext("/predict", this::handlePredict);
        server.createContext("/shutdown", this::handleShutdown);
        server.setExecutor(Executors.newFixedThreadPool(4));
        server.start();
        System.out.println("[" + serviceName + "] " + listeningAlgorithm + " listening on 127.0.0.1:" + port);
    }
    private void handleHealth(HttpExchange ex, String healthAlgorithm) throws IOException {
        JSONArray algorithms = new JSONArray();
        for (String code : supportedAlgorithms) {
            algorithms.put(code);
        }
        respond(ex, 200, new JSONObject()
                .put("status", "ok")
                .put("algorithm", healthAlgorithm)
                .put("algorithms", algorithms)
                .put("model_cache", modelCache.size()));
    }
    private void handleTrain(HttpExchange ex) throws IOException {
        try {
            JSONObject req = new JSONObject(readBody(ex));
            JSONObject metrics = executeTraining(req);
            respond(ex, 200, new JSONObject().put("success", true).put("metrics", metrics));
        } catch (Throwable e) {
            respond(ex, 500, new JSONObject().put("success", false).put("error", message(e)));
        } finally {
            modelCache.releaseModelCache("训练结束后");
        }
    }
    private JSONObject executeTraining(JSONObject req) throws Exception {
        String algorithmCode = algorithmResolver.apply(req);
        String datasetPath = req.getString("dataset_path");
        String modelSavePath = req.optString("model_save_path", "");
        if (modelSavePath.isEmpty()) {
            throw new IllegalArgumentException("缺少model_save_path");
        }
        modelCache.releaseModelCache("训练开始前");
        long started = System.nanoTime();
        Instances data = loadDataset(datasetPath);
        JSONObject parameters = req.optJSONObject("training_parameters");
        JSONObject effectiveParameters = parameters == null ? new JSONObject() : parameters;
        JSONObject quality = calculateQualityMetrics(
                classifierFactory.create(effectiveParameters, algorithmCode),// 先做交叉验证
                data,
                req.optJSONArray("risk_labels"));
        Classifier classifier = classifierFactory.create(effectiveParameters, algorithmCode);
        classifier.buildClassifier(data);
        SerializationHelper.write(modelSavePath, classifier);
        JSONArray distribution = classDistribution(data);
        JSONObject metrics = new JSONObject()
                .put("algorithm", algorithmCode)
                .put("accuracy", quality.get("accuracy"))
                .put("precision", quality.get("precision"))
                .put("recall", quality.get("recall"))
                .put("f1", quality.get("f1"))
                .put("specificity", quality.get("specificity"))
                .put("g_mean", quality.get("g_mean"))
                .put("risk_recall", quality.get("risk_recall"))
                .put("risk_f1", quality.get("risk_f1"))
                .put("cv_mean", quality.get("cv_mean"))
                .put("cv_std", quality.get("cv_std"))
                .put("quality_availability", quality.get("quality_availability"))
                .put("train_time_s", round((System.nanoTime() - started) / 1_000_000_000.0))
                .put("num_instances", data.numInstances())
                .put("num_attributes", data.numAttributes() - 1)
                .put("num_classes", data.numClasses())
                .put("class_distribution", distribution)
                .put("model_saved_to", modelSavePath)
                .put("dataset", datasetPath);
        metrics.put("training_parameters", parameters == null ? new JSONObject() : parameters);
        return metrics;
    }
    private void handlePredict(HttpExchange ex) throws IOException {
        try {
            JSONObject req = new JSONObject(readBody(ex));
            String algorithmCode = algorithmResolver.apply(req);
            String modelPath = req.getString("model_path");
            String arffPath = req.getString("arff_path");
            JSONObject features = req.optJSONObject("features");
            if (features == null) throw new IllegalArgumentException("缺少features字段");
            Classifier classifier = modelCache.loadModel(modelPath);
            Instances header = new DataSource(arffPath).getStructure();
            if (header.classIndex() < 0) header.setClassIndex(header.numAttributes() - 1);
            Instance instance = buildInstance(header, features);
            double[] dist = classifier.distributionForInstance(instance);
            int predicted = maxIndex(dist);
            JSONArray classes = new JSONArray();
            for (int i = 0; i < dist.length; i++) {
                classes.put(new JSONObject().put("class", header.classAttribute().value(i))
                        .put("probability", round(dist[i])));
            }
            JSONObject data = new JSONObject().put("prediction_label", header.classAttribute().value(predicted))
                    .put("probability", round(dist[predicted])).put("class_distribution", classes);
            try {
                data.put("feature_attribution", buildFeatureAttribution(classifier, instance, header, features));
            } catch (Exception ignored) {
                data.put("feature_attribution", new JSONArray());
            }
            JSONObject explain = explanationBuilder.build(
                    classifier, instance, header, req.optJSONArray("risk_labels"), dist,
                    algorithmCode);
            data.put("views", explain.getJSONArray("views"));
            data.put("view_weights", explain.getJSONArray("view_weights"));
            data.put("feature_evidence", explain.getJSONArray("feature_evidence"));
            data.put("algorithm_details", explain.getJSONObject("algorithm_details"));
            if (explain.has("calculation_method")) {
                data.put("calculation_method", explain.getString("calculation_method"));
            }
            respond(ex, 200, new JSONObject().put("success", true).put("data", data));
        } catch (Throwable e) {
            respond(ex, 500, new JSONObject().put("success", false).put("error", message(e)));
        }
    }
    private void handleShutdown(HttpExchange ex) throws IOException {
        respond(ex, 200, new JSONObject().put("status", "stopping"));
        new Thread(() -> System.exit(0), shutdownThreadName).start();
    }

    private static final class ModelCache {
        private static final double MODEL_HEAP_FACTOR = 1.4;
        private static final class CachedModel {
            final Classifier classifier;
            final long bytes;
            CachedModel(Classifier classifier, long bytes) {
                this.classifier = classifier;
                this.bytes = bytes;
            }
        }
        private final Map<String, CachedModel> models = // 按访问顺序排列
                Collections.synchronizedMap(new LinkedHashMap<String, CachedModel>(8, 0.75f, true));
        private final long budgetBytes;
        private final String logPrefix;
        public ModelCache(String budgetProperty, String serviceName) {
            budgetBytes = Long.getLong(budgetProperty,
                    Math.max(48L << 20, (long) (Runtime.getRuntime().maxMemory() * 0.55)));
            logPrefix = "[" + serviceName + "]";
        }
        public int size() {
            return models.size();
        }
        private long estimateModelBytes(String modelPath) {
            return (long) (new File(modelPath).length() * MODEL_HEAP_FACTOR);
        }
        private void evictFor(long incomingBytes) {
            synchronized (models) {
                long total = 0;
                for (CachedModel cached : models.values()) {
                    total += cached.bytes;
                }
                Iterator<Map.Entry<String, CachedModel>> it = models.entrySet().iterator();
                while (it.hasNext() && total + incomingBytes > budgetBytes) {
                    Map.Entry<String, CachedModel> eldest = it.next();
                    total -= eldest.getValue().bytes;
                    it.remove();
                    System.out.println(logPrefix + "缓存预算不足，淘汰最久未使用的模型: " + eldest.getKey());
                }
            }
        }
        public Classifier loadModel(String modelPath) throws Exception {
            CachedModel cached = models.get(modelPath);
            if (cached != null) {
                return cached.classifier;
            }
            long estimated = estimateModelBytes(modelPath);
            evictFor(estimated);
            Classifier classifier;
            try {
                classifier = (Classifier) SerializationHelper.read(modelPath);
            } catch (Exception e) {
                throw new RuntimeException("模型加载失败: " + e.getMessage(), e);
            }
            models.put(modelPath, new CachedModel(classifier, estimated));
            return classifier;
        }
        public void releaseModelCache(String phase) {
            int count;
            synchronized (models) {
                count = models.size();
                models.clear();
            }
            if (count > 0) {
                System.out.println(logPrefix + " " + phase + "释放模型缓存" + count + "个");
            }
            System.gc();
        }
    }
    public static JSONObject calculateQualityMetrics(
            Classifier untrainedTemplate, Instances data, JSONArray riskLabels) throws Exception {
        int folds = Math.min(10, data.numInstances());
        if (folds < 2) throw new IllegalArgumentException("交叉验证至少需要2条样本");
        Instances cvData = new Instances(data);
        Random random = new Random(1);
        cvData.randomize(random);
        if (cvData.classAttribute().isNominal()) cvData.stratify(folds);
        double[][] confusion = new double[data.numClasses()][data.numClasses()];
        double[] foldAccuracy = new double[folds];
        for (int fold = 0; fold < folds; fold++) {
            Classifier copy = AbstractClassifier.makeCopy(untrainedTemplate);
            Instances train = cvData.trainCV(folds, fold, random);
            Instances test = cvData.testCV(folds, fold);
            copy.buildClassifier(train);
            double correct = 0.0;
            double total = 0.0;
            for (int i = 0; i < test.numInstances(); i++) {
                Instance row = test.instance(i);
                if (row.classIsMissing()) continue;
                double[] distribution = copy.distributionForInstance(row);
                int predicted = maxIndex(distribution);
                int actual = (int) row.classValue();
                double weight = row.weight();
                confusion[actual][predicted] += weight;
                total += weight;
                if (actual == predicted) correct += weight;
            }
            foldAccuracy[fold] = total == 0.0 ? Double.NaN : correct / total;
        }
        double total = 0.0;
        double diagonal = 0.0;
        for (int actual = 0; actual < confusion.length; actual++) {
            for (int predicted = 0; predicted < confusion[actual].length; predicted++) {
                total += confusion[actual][predicted];
                if (actual == predicted) diagonal += confusion[actual][predicted];
            }
        }
        double weightedRecall = 0.0;
        double weightedPrecision = 0.0;
        double weightedF1 = 0.0;
        double weightedSpecificity = 0.0;
        for (int c = 0; c < confusion.length; c++) {
            double actualCount = 0.0;
            double predictedCount = 0.0;
            for (int i = 0; i < confusion.length; i++) {
                actualCount += confusion[c][i];
                predictedCount += confusion[i][c];
            }
            double tp = confusion[c][c];
            double fn = actualCount - tp;
            double fp = predictedCount - tp;
            double tn = total - tp - fn - fp;
            double weight = total == 0.0 ? 0.0 : actualCount / total;
            weightedRecall += weight * ratio(tp, tp + fn);
            weightedPrecision += weight * ratio(tp, tp + fp);
            weightedF1 += weight * f1(tp, fp, fn);
            weightedSpecificity += weight * ratio(tn, tn + fp);
        }
        boolean riskAvailable = false;
        double riskTp = 0.0;
        double riskActual = 0.0;
        double riskPredicted = 0.0;
        for (int actual = 0; actual < confusion.length; actual++) {
            boolean actualRisk = isRiskClass(data.classAttribute().value(actual), riskLabels);
            for (int predicted = 0; predicted < confusion[actual].length; predicted++) {
                boolean predictedRisk = isRiskClass(data.classAttribute().value(predicted), riskLabels);
                if (actualRisk) {
                    riskAvailable = true;
                    riskActual += confusion[actual][predicted];
                }
                if (predictedRisk) riskPredicted += confusion[actual][predicted];
                if (actualRisk && predictedRisk) riskTp += confusion[actual][predicted];
            }
        }
        double cvMean = mean(foldAccuracy);
        double cvStd = standardDeviation(foldAccuracy, cvMean);
        JSONObject quality = new JSONObject()
                .put("accuracy", round(ratio(diagonal, total)))
                .put("precision", round(weightedPrecision))
                .put("recall", round(weightedRecall))
                .put("f1", round(weightedF1))
                .put("specificity", round(weightedSpecificity))
                .put("g_mean", round(Math.sqrt(Math.max(0.0, weightedRecall * weightedSpecificity))))
                .put("risk_recall", riskAvailable ? round(ratio(riskTp, riskActual)) : JSONObject.NULL)
                .put("risk_f1", riskAvailable
                        ? round(f1(riskTp, riskPredicted - riskTp, riskActual - riskTp))
                        : JSONObject.NULL)
                .put("cv_mean", Double.isNaN(cvMean) ? JSONObject.NULL : round(cvMean))
                .put("cv_std", Double.isNaN(cvStd) ? JSONObject.NULL : round(cvStd))
                .put("quality_availability", new JSONObject()
                        .put("risk_recall", availability(riskAvailable, "训练请求未提供有效风险类别映射"))
                        .put("risk_f1", availability(riskAvailable, "训练请求未提供有效风险类别映射"))
                        .put("cv_mean", availability(!Double.isNaN(cvMean), "交叉验证均值不可用"))
                        .put("cv_std", availability(!Double.isNaN(cvStd), "交叉验证标准差不可用")));
        return quality;
    }
    public static boolean isRiskClass(String label, JSONArray riskLabels) {
        if (riskLabels == null) return false;
        for (int i = 0; i < riskLabels.length(); i++) {
            if (label.equals(String.valueOf(riskLabels.opt(i)))) return true;
        }
        return false;
    }
    private static double ratio(double numerator, double denominator) {
        return denominator == 0.0 ? 0.0 : numerator / denominator;
    }
    private static double f1(double tp, double fp, double fn) {
        double precision = ratio(tp, tp + fp);
        double recall = ratio(tp, tp + fn);
        return ratio(2.0 * precision * recall, precision + recall);
    }
    private static double mean(double[] values) {
        double sum = 0.0;
        int count = 0;
        for (double value : values) {
            if (!Double.isNaN(value)) { sum += value; count++; }
        }
        return count == 0 ? Double.NaN : sum / count;
    }
    private static double standardDeviation(double[] values, double mean) {
        if (Double.isNaN(mean)) return Double.NaN;
        double sum = 0.0;
        int count = 0;
        for (double value : values) {
            if (!Double.isNaN(value)) { double delta = value - mean; sum += delta * delta; count++; }
        }
        return count == 0 ? Double.NaN : Math.sqrt(sum / count);
    }
    public static JSONObject unavailable(String reason) {
        return new JSONObject().put("available", false).put("reason", reason);
    }
    public static JSONObject availability(boolean available, String reason) {
        return available
                ? new JSONObject().put("available", true).put("reason", JSONObject.NULL)
                : unavailable(reason);
    }
    public static JSONArray buildFeatureAttribution( // 只读的局部分析
            Classifier classifier, Instance instance, Instances header, JSONObject features) throws Exception {
        double[] original = classifier.distributionForInstance(instance);
        int predicted = maxIndex(original);
        ArrayList<JSONObject> items = new ArrayList<>();
        for (int i = 0; i < header.numAttributes(); i++) {
            if (i == header.classIndex() || instance.isMissing(i)) continue;
            Instance masked = new DenseInstance(instance);
            masked.setDataset(header);
            masked.setMissing(i);
            double[] changed = classifier.distributionForInstance(masked);
            double delta = original[predicted] - changed[predicted];
            Attribute attr = header.attribute(i);
            Object raw = features.has(attr.name()) ? features.get(attr.name()) : JSONObject.NULL;
            String processed = attr.isNominal() ? instance.stringValue(i) : String.valueOf(instance.value(i));
            items.add(new JSONObject()
                    .put("feature_name", attr.name())
                    .put("raw_value", raw)
                    .put("processed_value", processed)
                    .put("contribution", round(Math.abs(delta)))
                    .put("signed_contribution", round(delta))
                    .put("supports_predicted", delta >= 0));
        }
        items.sort(Comparator.comparingDouble(x -> -x.optDouble("contribution", 0.0)));
        JSONArray result = new JSONArray();
        int limit = Math.min(10, items.size());
        for (int i = 0; i < limit; i++) result.put(items.get(i).put("rank", i + 1));
        return result;
    }
    public static Instances loadDataset(String path) throws Exception {
        Instances data = new DataSource(path).getDataSet();
        if (data == null || data.numAttributes() < 2) throw new IllegalArgumentException("数据集字段不足");
        if (data.classIndex() < 0) data.setClassIndex(data.numAttributes() - 1);
        data.deleteWithMissingClass();
        if (!data.classAttribute().isNominal()) throw new IllegalArgumentException("分类标签必须是名义型字段");
        return data;
    }
    public static Instance buildInstance(Instances header, JSONObject features) {
        DenseInstance instance = new DenseInstance(header.numAttributes());
        instance.setDataset(header);
        int classIndex = header.classIndex();
        for (int i = 0; i < header.numAttributes(); i++) {
            if (i == classIndex) { instance.setMissing(i); continue; }
            Attribute attr = header.attribute(i);
            String name = attr.name();
            if (!features.has(name)) { instance.setMissing(i); continue; }
            Object value = features.get(name);
            if (value == null || JSONObject.NULL.equals(value) || String.valueOf(value).trim().isEmpty()) {
                instance.setMissing(i); continue;
            }
            try {
                if (attr.isNumeric()) {
                    instance.setValue(i, value instanceof Number ? ((Number) value).doubleValue()
                            : Double.parseDouble(String.valueOf(value).trim()));
                } else {
                    String label = String.valueOf(value);
                    if (attr.indexOfValue(label) >= 0) instance.setValue(i, label);
                    else instance.setMissing(i);
                }
            } catch (Exception ignored) { instance.setMissing(i); }
        }
        return instance;
    }
    public static JSONArray classDistribution(Instances data) {
        int[] counts = new int[data.numClasses()];
        for (int i = 0; i < data.numInstances(); i++) {
            counts[(int) data.instance(i).classValue()]++;
        }
        JSONArray distribution = new JSONArray();
        for (int i = 0; i < counts.length; i++) {
            distribution.put(new JSONObject()
                    .put("class", data.classAttribute().value(i))
                    .put("count", counts[i]));
        }
        return distribution;
    }
    public static int maxIndex(double[] probabilities) {
        int best = 0;
        for (int i = 1; i < probabilities.length; i++) {
            if (probabilities[i] > probabilities[best]) {
                best = i;
            }
        }
        return best;
    }
    public static double round(double value) { return Math.round(value * 10000.0) / 10000.0; }
    public static String message(Throwable e) { return e.getMessage() == null ? e.toString() : e.getMessage(); }
    public static String readBody(HttpExchange ex) throws IOException {
        return new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
    }
    public static void respond(HttpExchange ex, int code, JSONObject body) throws IOException {
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        ex.sendResponseHeaders(code, bytes.length);
        try (OutputStream output = ex.getResponseBody()) { output.write(bytes); }
    }
}
