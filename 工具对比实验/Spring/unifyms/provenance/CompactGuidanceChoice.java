package tuning;

import com.alibaba.fastjson2.*;
import java.util.*;

/** Lossless structural evidence packing. Full records remain in the window audit. */
public final class CompactGuidanceChoice {
    private CompactGuidanceChoice() {}
    public static JSONObject pack(JSONObject evidence) {
        // Live solutions contain Java maps/POJOs; saved audits contain JSONObjects.
        // Normalize a copy so both paths have identical traversal and null handling.
        evidence=JSON.parseObject(JSON.toJSONString(evidence,JSONWriter.Feature.WriteNulls));
        JSONObject out=new JSONObject();
        for(String k:Arrays.asList("contextHash","windowEvidenceHash","targetMetric","metricOrder","normalization","dependencySnapshotHash","consistencyNonDiscriminative"))
            if(evidence.containsKey(k))out.put(k,evidence.get(k));
        out.put("version",GuidanceClients.CHOICE_PROMPT_VERSION);
        out.put("encoding","chromosome: use cases then entities. Graph rows useCaseOperation=[uc index,op index], operationEntity=[uc index,op index,entity index]; integer i denotes stable uc:i/operation:i/entity:i. Nonstandard IDs remain strings. Every relation retained. Derive caller/provider and all remote edges from graph plus chromosome; checkSummary accounts for every checked edge, exceptions retain every failure/unknown. No remote edge list is needed twice. Summary is deterministic program evidence, not an LLM judgment. Missing checks mean unknown; remote access is legal; no behavior equivalence proof.");
        for(String k:Arrays.asList("base","reference")) {
            JSONObject row=evidence.getJSONObject(k);
            if(row!=null){JSONObject summary=fields(row,"chromosome","metrics","serviceCount","valid");
                JSONArray services=row.getJSONArray("services");int uc=0,en=0;
                if(services!=null){for(Object raw:services){JSONObject service=(JSONObject)raw;uc+=service.getJSONArray("useCases").size();en+=service.getJSONArray("entities").size();}summary.put("useCaseCount",uc);summary.put("entityCount",en);}
                out.put(k,summary);}
        }
        JSONObject graphs=new JSONObject(),choices=new JSONObject();out.put("graphs",graphs);out.put("candidates",choices);
        JSONObject originals=evidence.getJSONObject("choices");
        if(originals==null)throw new IllegalArgumentException("Missing choices");
        for(String id:new TreeSet<>(originals.keySet())) {
            if("KEEP".equals(id))continue;
            JSONObject c=originals.getJSONObject(id),v=fields(c,"normalizedLoss","rawMetricDelta","candidateHash");
            JSONObject solution=c.getJSONObject("solution");
            if(solution!=null)v.put("solution",fields(solution,"chromosome","metrics","serviceCount","valid"));
            JSONObject checks=c.getJSONObject("consistency");
            if(checks==null) {v.put("checksAvailable",false);choices.put(id,v);continue;}
            JSONArray uo=checks.getJSONArray("useCaseOperation"),oe=checks.getJSONArray("operationEntity");
            JSONObject graph=new JSONObject();JSONArray urows=new JSONArray(),erows=new JSONArray(),issues=new JSONArray();
            TreeSet<String> remote=new TreeSet<>();Map<String,Integer> statuses=new TreeMap<>();int preserved=0;
            if(uo!=null)for(Object raw:uo) {
                JSONObject r=(JSONObject)raw;urows.add(Arrays.asList(index(r.get("useCase"),"uc:"),index(r.get("operation"),"operation:")));
                if(Boolean.TRUE.equals(r.getBoolean("associationPreserved")))preserved++;
                else issues.add(r);
            }
            if(oe!=null)for(Object raw:oe) {
                JSONObject r=(JSONObject)raw;erows.add(Arrays.asList(index(r.get("useCase"),"uc:"),index(r.get("operation"),"operation:"),index(r.get("entity"),"entity:")));
                String status=r.getString("status");statuses.merge(String.valueOf(status),1,Integer::sum);
                if(!"SUPPORTED_STRUCTURALLY".equals(status)||!Boolean.TRUE.equals(r.getBoolean("dependencyPreserved")))issues.add(r);
                if(r.getBooleanValue("remote"))remote.add(JSON.toJSONString(Arrays.asList(r.get("caller"),r.get("provider"),r.get("entity"),status)));
            }
            graph.put("useCaseOperation",urows);graph.put("operationEntity",erows);
            // Equality, rather than a hash alone, prevents accidental graph conflation.
            String graphId=null;for(String key:new TreeSet<>(graphs.keySet()))if(graph.equals(graphs.getJSONObject(key))){graphId=key;break;}
            if(graphId==null){graphId="g"+graphs.size();graphs.put(graphId,graph);}
            v.put("graph",graphId);v.put("checksAvailable",uo!=null&&oe!=null);
            JSONObject summary=new JSONObject();summary.put("useCaseOperationCount",uo==null?null:uo.size());summary.put("preservedUseCaseOperationCount",preserved);
            summary.put("operationEntityCount",oe==null?null:oe.size());summary.put("operationEntityStatuses",statuses);summary.put("deterministicError",checks.get("deterministicError"));
            summary.put("uniqueRemoteSupportCount",remote.size());v.put("checkSummary",summary);v.put("exceptions",issues);
            choices.put(id,v);
        }
        // Selected IDs suffice: these candidates have already been removed from choices.
        JSONArray selected=new JSONArray();JSONArray prior=evidence.getJSONArray("alreadySelected");
        if(prior!=null)for(Object raw:prior)selected.add(((JSONObject)raw).get("id"));out.put("alreadySelected",selected);
        if(evidence.containsKey("elementNames"))out.put("elementNames",evidence.get("elementNames"));
        return out;
    }
    private static JSONObject fields(JSONObject source,String... names) {
        JSONObject result=new JSONObject();for(String name:names)if(source.containsKey(name))result.put(name,source.get(name));return result;
    }
    private static Object index(Object id,String prefix){String s=String.valueOf(id);if(s.startsWith(prefix))try{return Integer.valueOf(s.substring(prefix.length()));}catch(NumberFormatException ignored){}return id;}
}
