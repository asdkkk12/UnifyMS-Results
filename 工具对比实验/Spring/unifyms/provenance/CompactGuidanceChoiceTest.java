package tuning;

import com.alibaba.fastjson2.*;
import org.junit.jupiter.api.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.stream.Stream;
import static org.junit.jupiter.api.Assertions.*;

class CompactGuidanceChoiceTest {
    private JSONObject evidence(){
        JSONObject e=new JSONObject(),choices=new JSONObject();e.put("choices",choices);choices.put("KEEP","keep");
        JSONObject base=JSON.parseObject("{\"chromosome\":[0,1,0],\"metrics\":[2,0.3,0.4,0.5,0.6],\"serviceCount\":2}");e.put("base",base);
        for(String id:Arrays.asList("a","b")){
            JSONObject c=new JSONObject();c.put("solution",JSON.parseObject(base.toJSONString()));c.put("normalizedLoss",Arrays.asList(.1,.2,.3,.4,.5));
            JSONObject checks=new JSONObject();checks.put("deterministicError",false);
            checks.put("useCaseOperation",JSON.parseArray("[{\"useCase\":\"uc:0\",\"operation\":\"operation:3\",\"service\":0,\"associationPreserved\":true}]"));
            checks.put("operationEntity",JSON.parseArray("[{\"useCase\":\"uc:0\",\"operation\":\"operation:3\",\"entity\":\"entity:0\",\"caller\":0,\"provider\":1,\"remote\":true,\"dependencyPreserved\":true,\"status\":\"SUPPORTED_STRUCTURALLY\"}]"));
            c.put("consistency",checks);choices.put(id,c);
        }
        return e;
    }
    @Test void sharedGraphAndSmallCriteriaRetainEveryRelationAndMetric(){
        JSONObject original=evidence();String before=original.toJSONString();JSONObject req=GuidanceClients.choiceRequest(original,"fixed");
        assertEquals(before,original.toJSONString());JSONObject state=req.getJSONObject("state");assertEquals(1,state.getJSONObject("graphs").size());
        JSONObject graph=state.getJSONObject("graphs").getJSONObject("g0");assertEquals(Arrays.asList(0,3),graph.getJSONArray("useCaseOperation").getJSONArray(0));
        assertEquals(Arrays.asList(0,3,0),graph.getJSONArray("operationEntity").getJSONArray(0));
        JSONObject candidate=state.getJSONObject("candidates").getJSONObject("a");assertEquals(original.getJSONObject("base").get("metrics"),candidate.getJSONObject("solution").get("metrics"));
        assertEquals(1,candidate.getJSONObject("checkSummary").getIntValue("operationEntityCount"));assertEquals(1,candidate.getJSONObject("checkSummary").getIntValue("uniqueRemoteSupportCount"));
        assertFalse(candidate.containsKey("proposal"));assertFalse(candidate.containsKey("remoteSupport"));
        assertTrue(req.getJSONObject("questions").getJSONObject("configuration").getJSONObject("criteria").get("a") instanceof String);
    }
    @Test void exceptionsAndDifferentGraphsAreNeverDiscarded(){
        JSONObject e=evidence(),b=e.getJSONObject("choices").getJSONObject("b");JSONObject row=b.getJSONObject("consistency").getJSONArray("operationEntity").getJSONObject(0);
        row.put("entity","entity:1");row.put("status","DETERMINISTIC_ERROR");row.put("dependencyPreserved",false);
        JSONObject p=CompactGuidanceChoice.pack(e);assertEquals(2,p.getJSONObject("graphs").size());assertEquals(row,p.getJSONObject("candidates").getJSONObject("b").getJSONArray("exceptions").get(0));
        b.remove("consistency");assertFalse(CompactGuidanceChoice.pack(e).getJSONObject("candidates").getJSONObject("b").getBooleanValue("checksAvailable"));
    }
    @Test void liveSolutionsAndSavedJsonProduceIdenticalRequests(){
        JSONObject e=evidence();
        RunResult.SolutionRecord live=new RunResult.SolutionRecord();
        live.chromosome=new int[]{0,1,0};live.metrics=new double[]{2,.3,.4,.5,.6};live.serviceCount=2;
        Map<String,Object> service=new LinkedHashMap<>();service.put("useCases",Arrays.asList("u0","u1"));service.put("entities",Collections.singletonList("e0"));live.services.add(service);
        e.put("base",live);e.getJSONObject("choices").getJSONObject("a").put("solution",live);
        JSONObject saved=JSON.parseObject(JSON.toJSONString(e,JSONWriter.Feature.WriteNulls));
        JSONObject request=GuidanceClients.choiceRequest(e,"fixed");
        assertEquals(GuidanceClients.choiceRequest(saved,"fixed"),request);
        assertEquals(2,request.getJSONObject("state").getJSONObject("base").getIntValue("useCaseCount"));
        assertSame(live,e.get("base"));
    }
    @Test void oversizeIsRejectedBeforeAnyNetworkRequest(){
        JSONObject e=evidence();e.put("elementNames",Collections.singletonMap("uc:0",String.join("",Collections.nCopies(3000,"x"))));
        ExperimentConfig.JevOptions options=new ExperimentConfig.JevOptions();options.model="fixed";options.endpoint="https://example.invalid";options.guidanceMaxRequestBytes=1024;
        JSONObject r=GuidanceClients.choose(options,e);assertFalse(r.getBooleanValue("attempted"));assertTrue(r.getString("error").startsWith("LOCAL_REQUEST_BUDGET_EXCEEDED"));assertTrue(r.getIntValue("requestBytes")>1024);assertNull(r.get("httpStatus"));
    }
    /** Optional offline regression against actual saved audits, never contacts a provider. */
    @Test void savedRequestsFitLocalBudgetWithoutLosingRelations()throws Exception{
        String directory=System.getProperty("guidance.auditDirectory");Assumptions.assumeTrue(directory!=null);
        List<Integer> before=new ArrayList<>(),after=new ArrayList<>();
        try(Stream<Path> files=Files.walk(Paths.get(directory))){
            for(Path path:(Iterable<Path>)files.filter(p->p.getFileName().toString().matches("window-.*json"))::iterator){
                JSONObject window=JSON.parseObject(new String(Files.readAllBytes(path),StandardCharsets.UTF_8));
                for(Object raw:window.getJSONArray("selectionCalls")){
                    JSONObject call=(JSONObject)raw,e=call.getJSONObject("evidence"),frozen=window.getJSONObject("diagnostic").getJSONObject("frozenModel");
                    JSONObject names=new JSONObject();names.put("useCases",frozen.get("useCases"));names.put("entities",frozen.get("entities"));e.put("elementNames",names);
                    JSONObject request=GuidanceClients.choiceRequest(e,"jev-1.14.0"),packed=request.getJSONObject("state");int n=request.toJSONString().getBytes(StandardCharsets.UTF_8).length;
                    assertTrue(n<=new ExperimentConfig.JevOptions().guidanceMaxRequestBytes,path+": "+n);
                    for(String id:e.getJSONObject("choices").keySet())if(!"KEEP".equals(id)){
                        JSONObject source=e.getJSONObject("choices").getJSONObject(id).getJSONObject("consistency"),candidate=packed.getJSONObject("candidates").getJSONObject(id),graph=packed.getJSONObject("graphs").getJSONObject(candidate.getString("graph"));
                        assertEquals(source.getJSONArray("useCaseOperation").size(),graph.getJSONArray("useCaseOperation").size());
                        assertEquals(source.getJSONArray("operationEntity").size(),graph.getJSONArray("operationEntity").size());
                    }
                    JSONObject priorRequest=call.getJSONObject("response").getJSONObject("request");
                    before.add((priorRequest==null?e:priorRequest).toJSONString().getBytes(StandardCharsets.UTF_8).length);after.add(n);
                }
            }
        }
        assertFalse(after.isEmpty());Collections.sort(before);Collections.sort(after);
        System.out.println("OFFLINE_PACKING requests="+after.size()+" oldBytes="+before.get(0)+".."+before.get(before.size()-1)+" packedBytes="+after.get(0)+".."+after.get(after.size()-1));
    }
}
