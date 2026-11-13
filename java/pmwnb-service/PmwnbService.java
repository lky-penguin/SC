package weka.classifiers.bayes.PMWNB.service;
import com.security.bayes.service.AlgorithmServiceSupport;
import static com.security.bayes.service.AlgorithmServiceSupport.unavailable;
import org.json.JSONArray;
import org.json.JSONObject;
import weka.classifiers.bayes.PMWNB.PMWNB.PMWNB;
public final class PmwnbService { // PMWNB算法HTTP服务
    private static final String ALGORITHM = "PMWNB";

    private PmwnbService() {}

    public static void main(String[] args) throws Exception {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 12313;
        AlgorithmServiceSupport service = new AlgorithmServiceSupport(
                "PmwnbService", "pmwnb.modelCacheBudgetBytes", "pmwnb-shutdown",
                new String[] {ALGORITHM}, request -> ALGORITHM, (parameters, code) -> new PMWNB(),
                (classifier, instance, header, riskLabels, distribution, code) -> buildExplain(code));
        service.start(port, ALGORITHM, ALGORITHM);
    }

    private static JSONObject buildExplain(String algorithmCode) {
        JSONObject unavailable = unavailable("PMWNB暂未提供算法专属解释");
        return new JSONObject()
                .put("views", new JSONArray())
                .put("view_weights", new JSONArray())
                .put("feature_evidence", new JSONArray())
                .put("algorithm_details", new JSONObject()
                        .put("algorithm_code", algorithmCode)
                        .put("specific", unavailable)
                        .put("availability", unavailable));
    }
}
