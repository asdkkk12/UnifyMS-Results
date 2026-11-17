import tuning.*;
import tuning.RunResult.SolutionRecord;
import com.alibaba.fastjson2.*;
import java.nio.file.*;
import java.lang.reflect.*;
import java.util.*;
public class SpringFullAudit {
 static Method eval; static int checked=0;
 static SolutionRecord evaluate(int[] x)throws Exception{return (SolutionRecord)eval.invoke(null,(Object)x);}
 static void check(SolutionRecord s)throws Exception{SolutionRecord t=evaluate(s.chromosome);for(int j=0;j<5;j++)if(Math.abs(s.metrics[j]-t.metrics[j])>1e-12)throw new RuntimeException("Mismatch "+Arrays.toString(s.chromosome));checked++;}
 public static void main(String[] args)throws Exception{
  Path root=Paths.get(args[0]);Method load=LegacyAblationCli.class.getDeclaredMethod("load",Path.class);load.setAccessible(true);load.invoke(null,root.resolve("shared/protocol.json"));eval=LegacyAblationCli.class.getDeclaredMethod("evaluate",int[].class);eval.setAccessible(true);
  Quality.Normalization n=FilesIO.object(root.resolve("shared/calibration.json")).getObject("normalization",Quality.Normalization.class);
  JSONArray runs=new JSONArray();
  for(String arm:Arrays.asList("full"))for(long seed:new long[]{101,103,107,109,113,127,131,137,139,149}){
   Path file=Paths.get("/Users/yuanyaowu/Desktop/输出/Spring/unifyms/experiment/Spring/online-jev/guidance-jev/run-jev-"+seed+".json");JSONObject x=FilesIO.object(file);RunResult r=JSON.parseObject(x.getJSONObject("run").toJSONString(),RunResult.class);for(SolutionRecord row:r.population)check(row);for(SolutionRecord row:r.front)check(row);SolutionRecord rep=x.getObject("representative",SolutionRecord.class);check(rep);SolutionRecord chosen=Quality.representative(r.front,n);if(!Arrays.equals(chosen.chromosome,rep.chromosome))throw new RuntimeException("Representative mismatch");double hv=Quality.hv(r.front,n);if(Math.abs(hv-x.getDoubleValue("hv"))>1e-12)throw new RuntimeException("HV mismatch");JSONObject out=new JSONObject();out.put("arm",arm);out.put("seed",seed);out.put("metricsRecomputed",rep.metrics);out.put("representative",rep.chromosome);out.put("hvRecomputed",hv);runs.add(out);
  }
  JSONObject out=new JSONObject();out.put("status","success");out.put("savedSolutionsRecomputed",checked);out.put("runs",runs);FilesIO.write(Paths.get(args[1]),out);System.out.println("checked="+checked+" runs="+runs.size());LegacyAblationProtocol.reset();
 }
}
