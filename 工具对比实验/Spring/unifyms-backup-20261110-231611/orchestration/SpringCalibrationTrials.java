import tuning.*;
import com.alibaba.fastjson2.*;
import java.nio.file.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;

/** Run C1-C5 via the existing trial method while the sequential controller is paused. */
public class SpringCalibrationTrials {
 public static void main(String[] args)throws Exception {
  Path config=Paths.get(args[0]);ExperimentConfig cfg=FilesIO.read(config,ExperimentConfig.class);cfg.validate();
  Constructor<TuningCli> ctor=TuningCli.class.getDeclaredConstructor(Path.class,Map.class);ctor.setAccessible(true);
  Method trial=TuningCli.class.getDeclaredMethod("trial",ExperimentConfig.SystemInput.class,String.class,Path.class,RunConfig.class);trial.setAccessible(true);
  ExperimentConfig.SystemInput system=cfg.systems.get(0);String hash=FilesIO.inputHash(Paths.get(system.input));Path dir=Paths.get(cfg.outputDirectory).resolve(system.id);
  ExecutorService pool=Executors.newFixedThreadPool(3);List<Future<JSONObject>> futures=new ArrayList<>();long start=System.nanoTime();
  for(String id:Arrays.asList("C1","C2","C3","C4","C5")) {
   // Constructors run serially: their manifest write has the same frozen binding.
   TuningCli cli=ctor.newInstance(config,new LinkedHashMap<String,String>());
   RunConfig run=JSON.parseObject(JSON.toJSONString(cfg.candidate(id)),RunConfig.class);run.seed=11;run.evaluationBudget=1802000;
   futures.add(pool.submit(()->{
    long begun=System.nanoTime();RunResult result;
    try{result=(RunResult)trial.invoke(cli,system,hash,dir,run);}catch(InvocationTargetException e){throw new RuntimeException(e.getCause());}
    if(!"success".equals(result.status))throw new IllegalStateException(id+" failed");
    JSONObject row=new JSONObject();row.put("config",id);row.put("taskKey",result.taskKey);row.put("evaluations",result.evaluations);row.put("seconds",(System.nanoTime()-begun)/1e9);
    System.out.println(id+" complete");return row;
   }));
  }
  pool.shutdown();JSONArray rows=new JSONArray();for(Future<JSONObject> f:futures)rows.add(f.get());
  JSONObject out=new JSONObject();out.put("phase","C1-C5 parallel source trial orchestration");out.put("jobs",3);out.put("seconds",(System.nanoTime()-start)/1e9);out.put("trials",rows);
  FilesIO.write(Paths.get(args[1]),out);System.out.println("C1-C5 complete; resume the original controller to reuse these actual results.");
 }
}
