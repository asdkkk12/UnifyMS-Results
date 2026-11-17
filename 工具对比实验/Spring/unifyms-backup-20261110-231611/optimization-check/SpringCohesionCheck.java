import java.nio.file.*;
import java.util.*;
import GA.DiagramParser;
import Evaluation.QualityCalculate;
import Evaluation.LegacyQualityCalculate;

public class SpringCohesionCheck {
 public static void main(String[] args)throws Exception {
  tuning.ModelLoader.load(Paths.get(args[0]));
  Random rng=new Random(20261104);int cases=512;long oldNanos=0,newNanos=0;double checksum=0;
  for(int trial=0;trial<cases;trial++) {
   int n=DiagramParser.numofUC,e=DiagramParser.numofEntity,k=trial==0?1:trial==1?n:1+rng.nextInt(n);
   ArrayList<ArrayList<Integer>> ucs=new ArrayList<>(),entities=new ArrayList<>();
   for(int i=0;i<k;i++){ucs.add(new ArrayList<>());entities.add(new ArrayList<>());}
   for(int i=0;i<n;i++)ucs.get(i<k?i:rng.nextInt(k)).add(i);
   for(int i=0;i<e;i++)entities.get(rng.nextInt(k)).add(i);
   for(ArrayList<Integer> group:ucs)Collections.shuffle(group,rng);
   long start=System.nanoTime();double[] original={LegacyQualityCalculate.functionCoupling(ucs,entities),LegacyQualityCalculate.functionalCohesion(ucs,entities),LegacyQualityCalculate.Modilarity(ucs,entities),LegacyQualityCalculate.Instability(ucs,entities),LegacyQualityCalculate.structureCohesion(ucs)-LegacyQualityCalculate.structureCoupling(ucs)};oldNanos+=System.nanoTime()-start;
   start=System.nanoTime();double[] optimized={QualityCalculate.functionCoupling(ucs,entities),QualityCalculate.functionalCohesion(ucs,entities),QualityCalculate.Modilarity(ucs,entities),QualityCalculate.Instability(ucs,entities),QualityCalculate.structureCohesion(ucs)-QualityCalculate.structureCoupling(ucs)};newNanos+=System.nanoTime()-start;
   for(int i=0;i<5;i++)if(Double.doubleToLongBits(original[i])!=Double.doubleToLongBits(optimized[i]))throw new AssertionError("Case "+trial+" objective "+i);
   if(!Arrays.deepEquals(LegacyQualityCalculate.generateInterface(ucs,entities),QualityCalculate.generateInterface(ucs,entities)))throw new AssertionError("Interface flags "+trial);
   checksum+=original[1];
  }
  String report="{\"all_five_objectives_and_interfaces\":true,\"cases\":"+cases+",\"bitwise_equal\":true,\"legacy_seconds\":"+(oldNanos/1e9)+",\"optimized_seconds\":"+(newNanos/1e9)+",\"checksum\":"+checksum+"}";
  Files.write(Paths.get(args[1]),report.getBytes(java.nio.charset.StandardCharsets.UTF_8));System.out.println(report);
 }
}
