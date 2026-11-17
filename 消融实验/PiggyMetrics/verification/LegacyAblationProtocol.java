package tuning;

import com.alibaba.fastjson2.*;
import java.nio.file.*;

/** Explicit, process-local compatibility policy. Never enabled by normal experiment entrypoints. */
public final class LegacyAblationProtocol {
    public static final String VERSION="cocome-legacy-three-ablation-v1";
    public static final String METRICS="paper-ieee-eq5-21-v1";
    public static final String INPUT="b0d36476c404b6692ddd7ceb82089cde7388e2804d26b2580cdf89e06e075f1c";
    public static final String LIBRARY_VERSION="library-frozen-three-ablation-v1";
    public static final String LIBRARY_INPUT="2f46f25515e81daff152fa32ce0f572c6f27f726243e970040236e3d20034b79";
    public static final String ATM_VERSION="atm-frozen-three-ablation-v1";
    public static final String ATM_INPUT="57de92c76df61ec66659f4d34949207f172a858f713820b1f8ddb38291900e10";
    public static final String LOAN_VERSION="loan-frozen-three-ablation-v1";
    public static final String LOAN_INPUT="e666fbd5bb2b797d77a1bbdcc6731e1caf0dd99ed28dc3e29c5f79877ba563fa";
    public static final String TAXI_VERSION="taxi-frozen-three-ablation-v1";
    public static final String TAXI_INPUT="970acf9f42c1daed1596f693c35ee1ccaa0fd5cf0b0f7013309add7ac177e1c3";
    public static final String LIGHT_VERSION="light-reading-frozen-three-ablation-v1";
    public static final String LIGHT_INPUT="ea351f34e84f80608396be88552199eaadf18e39a5778f1738b8adbd4cc49530";
    public static final String PIGGY_VERSION="piggymetrics-frozen-three-ablation-v1";
    public static final String PIGGY_INPUT="88bcf174ce5a8d9c719dda60f8f9f3380005c52064b48bd5b213c5bb0cec7af2";
    private static JSONObject policy;
    private LegacyAblationProtocol() {}
    public static boolean enabled(){return policy!=null;}
    public static void activate(Path file)throws Exception {
        JSONObject p=FilesIO.object(file);
        boolean cocome=VERSION.equals(p.getString("protocolVersion"))&&METRICS.equals(p.getString("metricVersion"))&&INPUT.equals(p.getString("inputHash"));
        boolean library=LIBRARY_VERSION.equals(p.getString("protocolVersion"))&&Evaluation.PaperMetrics.VERSION.equals(p.getString("metricVersion"))&&LIBRARY_INPUT.equals(p.getString("inputHash"))&&"C3".equals(p.getString("selectedConfig"));
        boolean atm=ATM_VERSION.equals(p.getString("protocolVersion"))&&Evaluation.PaperMetrics.VERSION.equals(p.getString("metricVersion"))&&ATM_INPUT.equals(p.getString("inputHash"))&&"C0".equals(p.getString("selectedConfig"))&&"filtered-comment-reader-v1".equals(p.getString("historicalParser"));
        boolean loan=LOAN_VERSION.equals(p.getString("protocolVersion"))&&Evaluation.PaperMetrics.VERSION.equals(p.getString("metricVersion"))&&LOAN_INPUT.equals(p.getString("inputHash"))&&"C5".equals(p.getString("selectedConfig"))&&"filtered-comment-reader-v1".equals(p.getString("historicalParser"));
        boolean taxi=TAXI_VERSION.equals(p.getString("protocolVersion"))&&Evaluation.PaperMetrics.VERSION.equals(p.getString("metricVersion"))&&TAXI_INPUT.equals(p.getString("inputHash"))&&"C5".equals(p.getString("selectedConfig"))&&"filtered-comment-reader-v1".equals(p.getString("historicalParser"));
        boolean light=LIGHT_VERSION.equals(p.getString("protocolVersion"))&&Evaluation.PaperMetrics.VERSION.equals(p.getString("metricVersion"))&&LIGHT_INPUT.equals(p.getString("inputHash"))&&"C3".equals(p.getString("selectedConfig"))&&"filtered-comment-reader-v1".equals(p.getString("historicalParser"));
        boolean piggy=PIGGY_VERSION.equals(p.getString("protocolVersion"))&&Evaluation.PaperMetrics.VERSION.equals(p.getString("metricVersion"))&&PIGGY_INPUT.equals(p.getString("inputHash"))&&"C5".equals(p.getString("selectedConfig"))&&"filtered-comment-reader-v1".equals(p.getString("historicalParser"));
        if(!cocome&&!library&&!atm&&!loan&&!taxi&&!light&&!piggy)throw new IllegalArgumentException("Unsupported frozen case protocol");
        for(String key:new String[]{"generationInstructions","choiceInstructions","onlineInstructions","choicePromptVersion"})if(p.getString(key)==null)throw new IllegalArgumentException("Missing historical "+key);
        policy=p;
    }
    public static void reset(){policy=null;}
    public static String metricVersion(){return enabled()?policy.getString("metricVersion"):Evaluation.PaperMetrics.VERSION;}
    public static String inputHash(){return enabled()?policy.getString("inputHash"):INPUT;}
    public static String protocolVersion(){return enabled()?policy.getString("protocolVersion"):VERSION;}
    public static String selectedConfig(){return enabled()?policy.getString("selectedConfig")==null?"C5":policy.getString("selectedConfig"):"C5";}
    public static double isolatedScore(){return enabled()&&METRICS.equals(metricVersion())?1:0;}
    /** Historical Library artifacts were produced before comment filtering was introduced. */
    public static boolean historicalRawComments(){return enabled()&&LIBRARY_VERSION.equals(protocolVersion())&&"raw-comment-reader-v1".equals(policy.getString("historicalParser"));}
    public static String choiceVersion(){return enabled()?policy.getString("choicePromptVersion"):GuidanceClients.CHOICE_PROMPT_VERSION;}
    public static String generationInstructions(){return enabled()?policy.getString("generationInstructions"):GuidanceEvidence.GENERATION_INSTRUCTIONS;}
    public static String onlineInstructions(){return enabled()?policy.getString("onlineInstructions"):OnlineJevClient.INSTRUCTIONS;}
    public static JSONArray metricDefinitions(){return JSON.parseArray(policy.getJSONArray("metricDefinitions").toJSONString());}
    public static JSONObject choiceRequest(JSONObject evidence,String model){
        JSONObject question=new JSONObject();question.put("type","choice");question.put("instructions",policy.getString("choiceInstructions"));question.put("criteria",evidence.get("choices"));
        JSONObject request=new JSONObject();request.put("model",model);request.put("state",evidence);JSONObject questions=new JSONObject();questions.put("configuration",question);request.put("questions",questions);return request;
    }
}
