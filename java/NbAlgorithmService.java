package com.security.bayes.nbservice;
import com.security.bayes.service.AlgorithmServiceSupport;
import static com.security.bayes.service.AlgorithmServiceSupport.availability;
import static com.security.bayes.service.AlgorithmServiceSupport.isRiskClass;
import static com.security.bayes.service.AlgorithmServiceSupport.maxIndex;
import static com.security.bayes.service.AlgorithmServiceSupport.round;
import static com.security.bayes.service.AlgorithmServiceSupport.unavailable;
import org.json.JSONArray;
import org.json.JSONObject;
import weka.classifiers.Classifier;
import weka.classifiers.meta.FilteredClassifier;
import weka.classifiers.zh.A2WNB.A2WNB;
import weka.classifiers.zh.A2WNB.RODE;
import weka.classifiers.zh.CAVWNB.CAVWNB;
import weka.classifiers.zh.CAVWNB.WANBDistribution;
import weka.classifiers.zh.MVCAVWNB.EMAWNB;
import weka.classifiers.zh.MVCAVWNB.MVCAVWNB;
import weka.classifiers.mkx.DIWNB.DIWNB_HE;
import weka.classifiers.bayes.FTAWNB;
import weka.classifiers.zh.FLNB.FLNB;
import weka.classifiers.zh.KFDB.KFDB;
import weka.core.Attribute;
import weka.core.DenseInstance;
import weka.core.Instance;
import weka.core.Instances;
import weka.filters.unsupervised.attribute.Discretize;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
public final class NbAlgorithmService { // 真实NB算法HTTP服务
    private static final String[] SUPPORTED_ALGORITHMS = {
            "A2WNB", "CAVWNB", "DIWNB", "MAWNB", "EMAWNB",
            "KFDB", "FLNB", "FTAWNB"
    };
    private static String defaultAlgorithmCode = ""; // 默认值
    private NbAlgorithmService() {}
    public static void main(String[] args) throws Exception {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 12315;
        defaultAlgorithmCode = args.length > 1 ? args[1].toUpperCase(Locale.ROOT) : "";
        if (!defaultAlgorithmCode.isEmpty()) {
            classNameFor(defaultAlgorithmCode);
        }
        for (String code : SUPPORTED_ALGORITHMS) { // 加载全部算法
            Class.forName(classNameFor(code));
        }
        AlgorithmServiceSupport service = new AlgorithmServiceSupport(
                "NbAlgorithmService", "nb.modelCacheBudgetBytes", "nb-shutdown",
                SUPPORTED_ALGORITHMS, NbAlgorithmService::resolveAlgorithmCode,
                NbAlgorithmService::createClassifier, NbAlgorithmService::buildExplain);
        service.start(port, defaultAlgorithmCode.isEmpty() ? "MULTI" : defaultAlgorithmCode,
                defaultAlgorithmCode.isEmpty() ? "多算法模式" : defaultAlgorithmCode);
    }
    private static String resolveAlgorithmCode(JSONObject req) {
        String code = req.optString("algorithm_code", "").trim();
        if (code.isEmpty()) {
            code = defaultAlgorithmCode;
        }
        if (code.isEmpty()) {
            throw new IllegalArgumentException("缺少 algorithm_code");
        }
        code = code.toUpperCase(Locale.ROOT);
        classNameFor(code);
        return code;
    }
    private static String classNameFor(String code) {
        switch (code) {
            case "A2WNB": return "weka.classifiers.zh.A2WNB.A2WNB";
            case "CAVWNB": return "weka.classifiers.zh.CAVWNB.CAVWNB";
            case "DIWNB": return "weka.classifiers.mkx.DIWNB.DIWNB_HE";
            case "MAWNB": return "weka.classifiers.zh.MVCAVWNB.MVCAVWNB";
            case "EMAWNB": return "weka.classifiers.zh.MVCAVWNB.EMAWNB";
            case "KFDB": return "weka.classifiers.zh.KFDB.KFDB";
            case "FLNB": return "weka.classifiers.zh.FLNB.FLNB";
            case "FTAWNB": return "weka.classifiers.bayes.FTAWNB";
            default: throw new IllegalArgumentException("不支持的算法: " + code);
        }
    }
    private static JSONObject buildExplain(
            Classifier classifier, Instance instance, Instances header,
            JSONArray riskLabels, double[] finalDistribution, String algorithmCode) {
        JSONObject explain = new JSONObject();
        explain.put("views", new JSONArray());
        explain.put("view_weights", new JSONArray());
        explain.put("feature_evidence", new JSONArray());
        JSONObject unavailable = unavailable("算法专属解释提取失败");
        explain.put("algorithm_details", new JSONObject()
                .put("algorithm_code", algorithmCode)
                .put("specific", unavailable)
                .put("availability", unavailable));
        try {
            if (!(classifier instanceof FilteredClassifier)) {
                return explain;
            }
            FilteredClassifier fc = (FilteredClassifier) classifier;
            Classifier base = fc.getClassifier();
            if (base == null) {
                return explain;
            }
            Instance disc = instance;
            if (fc.getFilter() != null) {
                fc.getFilter().input(instance);
                disc = fc.getFilter().output();
            }
            JSONArray views = new JSONArray();
            JSONArray viewWeights = new JSONArray();
            JSONArray featureEvidence = new JSONArray();
            String calculationMethod = null;
            JSONObject specific = new JSONObject();
            if (base instanceof CAVWNB) {
                CAVWNB cav = (CAVWNB) base; // 单视图
                featureEvidence = buildCavwnbEvidence(cav, disc, header);
                specific.put("feature_evidence", featureEvidence)
                        .put("available", featureEvidence.length() > 0);
                if (featureEvidence.length() == 0) specific.put("reason", "未提供有效特征值证据");
                calculationMethod = "类×属性值权重×对数条件概率";
            } else if (base instanceof MVCAVWNB) {
                MVCAVWNB mv = (MVCAVWNB) base;
                JSONObject original = viewObj("原始属性视图", mv.classifier_view1.distributionForInstance(disc), header);
                JSONObject spode = viewObj("SPODE标签视图", mv.distributionForInstance_SPODE_Label(disc), header);
                JSONObject randomForest = viewObj("RF标签视图", mv.distributionForInstance_RT_Label(disc), header);
                views.put(original).put(spode).put(randomForest);
                specific.put("original_view", original)
                        .put("spode_view", spode)
                        .put("random_forest_view", randomForest)
                        .put("available", true);
                double third = 1.0 / 3.0;
                viewWeights.put(third).put(third).put(third);
                if (mv.classifier_view1 instanceof CAVWNB) {
                    featureEvidence = buildCavwnbEvidence((CAVWNB) mv.classifier_view1, disc, header);
                }
                calculationMethod = "类×属性值权重×对数条件概率";
            } else if (base instanceof EMAWNB) {
                EMAWNB ema = (EMAWNB) base;
                JSONObject original = viewObj("原始属性视图", ema.distributionForInstance1(disc), header);
                JSONObject spode = viewObj("SPODE标签视图", ema.distributionForInstance2(disc), header);
                JSONObject randomForest = viewObj("RF标签视图", ema.distributionForInstance3(disc), header);
                views.put(original).put(spode).put(randomForest);
                double weightSum = ema.w_view1 + ema.w_view2 + ema.w_view3;
                if (weightSum > 0) {
                    viewWeights.put(round(ema.w_view1 / weightSum))
                            .put(round(ema.w_view2 / weightSum))
                            .put(round(ema.w_view3 / weightSum));
                } else {
                    double equal = round(1.0 / 3.0);
                    viewWeights.put(equal).put(equal).put(equal);
                }
                specific.put("dynamic_view_weights", viewWeights)
                        .put("before_fusion", views)
                        .put("after_fusion", viewObj("融合后", finalDistribution, header))
                        .put("view_conflict", viewConflict(views))
                        .put("available", true);
                if (ema.classifier_view1 instanceof CAVWNB) {
                    featureEvidence = buildCavwnbEvidence((CAVWNB) ema.classifier_view1, disc, header);
                }
                calculationMethod = "类×属性值权重×对数条件概率";
            } else if (base instanceof DIWNB_HE) {
                DIWNB_HE diwnb = (DIWNB_HE) base; // 双视图：原始视图+生成视图
                JSONObject original = viewObj("原始视图", diwnb.distributionForView1(disc), header);
                JSONObject knn = viewObj("KNN 生成视图", diwnb.distributionForView2(disc), header);
                views.put(original).put(knn);
                double[] vw = diwnb.getViewWeightsForReport();
                viewWeights.put(round(vw[0])).put(round(vw[1]));
                JSONArray ks = new JSONArray();
                for (int value : diwnb.getKValuesForReport()) ks.put(value);
                JSONArray ratios = new JSONArray();
                for (double[] row : diwnb.getNeighborClassRatiosForReport(disc)) {
                    JSONArray values = new JSONArray();
                    for (double value : row) values.put(round(value));
                    ratios.put(values);
                }
                specific.put("original_view", original)
                        .put("knn_view", knn)
                        .put("k", ks)
                        .put("neighbor_class_ratios", ratios)
                        .put("consistency", viewConflict(views))
                        .put("available", true);
                if (riskLabels != null && ks.length() > 0) {
                    double riskRatio = 0.0;
                    int rows = 0;
                    for (int i = 0; i < ratios.length(); i++) {
                        JSONArray row = ratios.getJSONArray(i);
                        double total = 0.0;
                        for (int c = 0; c < row.length(); c++) {
                            if (isRiskClass(header.classAttribute().value(c), riskLabels)) {
                                total += row.getDouble(c);
                            }
                        }
                        riskRatio += total;
                        rows++;
                    }
                    specific.put("neighbor_risk_ratio", rows == 0 ? JSONObject.NULL : round(riskRatio / rows));
                }
            } else if (base instanceof A2WNB) {
                A2WNB a2 = (A2WNB) base;
                double[] original = a2.getOriginalDistributionForReport(disc);
                double[] enhanced = a2.getEnhancedDistributionForReport(disc);
                JSONArray originalAttributes = buildA2FeatureAttribution(
                        a2, instance, disc, header, featuresFromInstance(instance, header), false);
                JSONArray enhancedAttributes = buildA2FeatureAttribution(
                        a2, instance, disc, header, featuresFromInstance(instance, header), true);
                JSONArray enhancedValues = new JSONArray();
                for (String value : a2.getEnhancedAttributeValuesForReport(disc)) {
                    enhancedValues.put(value);
                }
                JSONArray probabilityChange = new JSONArray();
                for (int i = 0; i < original.length; i++) {
                    probabilityChange.put(new JSONObject()
                            .put("class", header.classAttribute().value(i))
                            .put("original_probability", round(original[i]))
                            .put("enhanced_probability", round(enhanced[i]))
                            .put("delta", round(enhanced[i] - original[i])));
                }
                JSONObject rode = new JSONObject()
                        .put("available", a2.getRodeModelCountForReport() > 0)
                        .put("model_count", a2.getRodeModelCountForReport())
                        .put("task", a2.getRodeTaskForReport());
                if (!rode.optBoolean("available")) rode.put("reason", "RODE未完成训练");
                specific.put("original_attributes", originalAttributes)
                        .put("enhanced_attributes", new JSONObject()
                                .put("values", enhancedValues)
                                .put("contributions", enhancedAttributes))
                        .put("probability_change", probabilityChange)
                        .put("rode", rode)
                        .put("available", true);
            } else if (base instanceof KFDB) {
                KFDB kfdb = (KFDB) base;
                JSONObject full = viewObj("KFDB依赖结构视图", finalDistribution, header);
                views.put(full);
                specific.put("full_view", full)
                        .put("model_score", kfdb.getMS())
                        .put("max_parents", kfdb.getMaxParentsForReport())
                        .put("available", true);
                calculationMethod = "K自由依赖贝叶斯分类器：按属性依赖结构聚合条件概率";
            } else if (base instanceof FLNB) {
                FLNB flnb = (FLNB) base;
                JSONObject full = viewObj("FLNB懒惰相似度视图", finalDistribution, header);
                views.put(full);
                specific.put("full_view", full)
                        .put("weight_scheme", flnb.getWeightScheme())
                        .put("available", true);
                calculationMethod = "基于频率的消极加权朴素贝叶斯：训练样本按相似度加权后估计条件概率";
            } else if (base instanceof FTAWNB) {
                JSONObject full = viewObj("FTAWNB属性加权视图", finalDistribution, header);
                views.put(full);
                specific.put("full_view", full)
                        .put("available", true);
                calculationMethod = "基于概率微调的属性加权朴素贝叶斯：互信息微调属性权重后估计条件概率";
            }
            explain.put("views", views);
            explain.put("view_weights", viewWeights);
            explain.put("feature_evidence", featureEvidence);
            explain.put("algorithm_details", new JSONObject()
                    .put("algorithm_code", algorithmCode)
                    .put("specific", specific)
                    .put("availability", availability(
                            specific.optBoolean("available", true),
                            specific.optString("reason", "算法专属解释不可用"))));
            if (calculationMethod != null) {
                explain.put("calculation_method", calculationMethod);
            }
        } catch (Exception ignored) {
        }
        return explain;
    }
    private static JSONObject viewConflict(JSONArray views) {
        Set<String> labels = new HashSet<>();
        JSONArray labelArray = new JSONArray();
        for (int i = 0; i < views.length(); i++) {
            String label = views.getJSONObject(i).optString("predicted_label", "");
            if (!label.isEmpty() && labels.add(label)) labelArray.put(label);
        }
        return new JSONObject().put("has_conflict", labels.size() > 1).put("labels", labelArray);
    }
    private static JSONObject featuresFromInstance(Instance instance, Instances header) {
        JSONObject features = new JSONObject();
        for (int i = 0; i < header.numAttributes(); i++) {
            if (i == header.classIndex() || instance.isMissing(i)) continue;
            Attribute attr = header.attribute(i);
            if (attr.isNominal()) features.put(attr.name(), instance.stringValue(i));
            else features.put(attr.name(), instance.value(i));
        }
        return features;
    }
    private static JSONArray buildA2FeatureAttribution(
            A2WNB a2, Instance rawInstance, Instance discreteInstance, Instances header,
            JSONObject features, boolean enhanced)
            throws Exception {
        double[] original = enhanced
                ? a2.getEnhancedDistributionForReport(discreteInstance)
                : a2.getOriginalDistributionForReport(discreteInstance);
        int predicted = maxIndex(original);
        ArrayList<JSONObject> items = new ArrayList<>();
        for (int i = 0; i < header.numAttributes(); i++) {
            if (i == header.classIndex() || rawInstance.isMissing(i)) continue;
            Instance masked = new DenseInstance(discreteInstance);
            masked.setDataset(discreteInstance.dataset());
            masked.setMissing(i);
            double[] changed = enhanced
                    ? a2.getEnhancedDistributionForReport(masked)
                    : a2.getOriginalDistributionForReport(masked);
            double delta = original[predicted] - changed[predicted];
            Attribute attr = header.attribute(i);
            Object raw = features.has(attr.name()) ? features.get(attr.name()) : JSONObject.NULL;
            String processed = attr.isNominal() ? rawInstance.stringValue(i) : String.valueOf(rawInstance.value(i));
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
        for (int i = 0; i < Math.min(10, items.size()); i++) {
            result.put(items.get(i).put("rank", i + 1));
        }
        return result;
    }
    private static JSONObject viewObj(String name, double[] dist, Instances header) {
        JSONObject obj = new JSONObject().put("name", name);
        JSONArray arr = new JSONArray();
        int predicted = maxIndex(dist);
        for (int i = 0; i < dist.length; i++) {
            arr.put(new JSONObject().put("class", header.classAttribute().value(i))
                    .put("probability", round(dist[i])));
        }
        obj.put("predicted_label", header.classAttribute().value(predicted));
        return obj.put("distribution", arr);
    }
    private static JSONArray buildCavwnbEvidence(CAVWNB cav, Instance disc, Instances header) throws Exception {
        WANBDistribution wd = cav.geDistribution();
        if (wd == null) {
            return new JSONArray();
        }
        double[] weights = wd.getWeights();       // 长度等于属性取值总数乘以类别数
        int[] card = wd.getCardinalities();       // 每个属性的取值数
        int[] offset = wd.getOffset();            // 每个属性在权重数组中的偏移
        double[][][] theta = wd.getThetaUC();     // 按属性、类别和属性取值索引的条件概率P(x_u|class)
        int attrValueCounts = wd.getAttValueCounts();
        int nc = theta[0].length;
        JSONArray arr = new JSONArray();
        for (int u = 0; u < card.length; u++) {
            if (disc.isMissing(u)) {
                continue;
            }
            int v = (int) disc.value(u);
            if (v < 0 || v >= card[u]) {
                continue;
            }
            JSONObject feat = new JSONObject();
            feat.put("attribute", disc.attribute(u).name());
            feat.put("value", disc.attribute(u).value(v));
            feat.put("view", "原始属性视图");
            JSONArray contribs = new JSONArray();
            for (int c = 0; c < nc; c++) {
                double w = weights[attrValueCounts * c + offset[u] + v];
                double p = theta[u][c][v];
                double logp = Math.log(Math.max(p, 1e-75));
                contribs.put(new JSONObject()
                        .put("class", header.classAttribute().value(c))
                        .put("weight", round(w))
                        .put("cond_prob", round(p))
                        .put("contribution", round(w * logp)));
            }
            feat.put("class_contributions", contribs);
            arr.put(feat);
        }
        return arr;
    }
    private static Classifier createClassifier(JSONObject parameters, String algorithmCode)
            throws Exception {
        Classifier base = (Classifier) Class.forName(classNameFor(algorithmCode))
                .getDeclaredConstructor().newInstance();
        applyAlgorithmParameters(base, parameters);
        return new FilteredClassifierWithDiscretize(base, parameters);
    }
    private static void applyAlgorithmParameters(Classifier base, JSONObject parameters) throws Exception {
        if (base instanceof CAVWNB) {
            CAVWNB cav = (CAVWNB) base;
            if (parameters.has("objective")) cav.setObjectiveFunction(parameters.getString("objective"));
            if (parameters.has("regularizer")) cav.setRegularizer(parameters.getString("regularizer"));
            if (parameters.has("regularization_lambda")) {
                cav.setRegularizationLambda(parameters.getDouble("regularization_lambda"));
            }
        } else if (base instanceof A2WNB) {
            A2WNB a2 = (A2WNB) base;
            if (parameters.has("rode_task")) {
                Classifier first = a2.getClassifier();
                if (!(first instanceof RODE)) {
                    throw new IllegalArgumentException("A2WNB的第一阶段分类器必须是RODE");
                }
                ((RODE) first).setTask(parameters.getInt("rode_task"));
            }
        } else if (base instanceof FLNB) {
            FLNB flnb = (FLNB) base;
            if (parameters.has("weight_scheme")) {
                flnb.setWeightScheme(parameters.getString("weight_scheme"));
            }
        } else if (base instanceof KFDB) {
            KFDB kfdb = (KFDB) base;
            if (parameters.has("model_score")) {
                kfdb.set_m_S(parameters.getString("model_score"));
            }
            if (parameters.has("max_parents")) {
                kfdb.setK(parameters.getInt("max_parents"));
            }
        }
    }
    private static final class FilteredClassifierWithDiscretize extends FilteredClassifier { // 对数值属性做离散化
        private static final long serialVersionUID = 1L;
        FilteredClassifierWithDiscretize(Classifier base, JSONObject parameters) throws Exception {
            setClassifier(base);
            Discretize discretize = new Discretize();
            discretize.setUseBinNumbers(true);
            if (parameters.has("discrete_bins")) {
                discretize.setBins(parameters.getInt("discrete_bins"));
            }
            if (parameters.has("discrete_method")) {
                String method = parameters.getString("discrete_method");
                discretize.setUseEqualFrequency("equal_freq".equalsIgnoreCase(method));
            }
            setFilter(discretize);
        }
    }
}
