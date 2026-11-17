package tuning;
import com.alibaba.fastjson2.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/** One request per call, bounded wall time, no redirects/retries/model fallback. */
public final class GuidanceClients {
    private GuidanceClients(){}
    public static JSONObject exchange(String endpoint,String key,int timeout,JSONObject request) {
        JSONObject audit=new JSONObject();audit.put("status","failed");audit.put("attempted",false);audit.put("request",request);audit.put("totalTokens",null);
        long start=System.nanoTime();AtomicReference<HttpURLConnection> active=new AtomicReference<>();ExecutorService pool=null;
        try {
            if(key==null||key.trim().isEmpty())throw new IOException("Missing runtime credential");
            URL url=new URL(endpoint);boolean local=Arrays.asList("localhost","127.0.0.1","::1","[::1]").contains(url.getHost());
            if(url.getUserInfo()!=null || !("https".equals(url.getProtocol()) || local&&"http".equals(url.getProtocol())))throw new IOException("HTTPS without URL credentials required");
            pool=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"guidance-request");t.setDaemon(true);return t;});
            audit.put("attempted",true);
            Future<JSONObject> f=pool.submit(()->{
                HttpURLConnection c=(HttpURLConnection)url.openConnection();active.set(c);
                try {
                    c.setInstanceFollowRedirects(false);c.setConnectTimeout(timeout);c.setReadTimeout(timeout);c.setRequestMethod("POST");
                    c.setRequestProperty("Authorization","Bearer "+key);c.setRequestProperty("Content-Type","application/json");c.setDoOutput(true);
                    try(OutputStream out=c.getOutputStream()){out.write(request.toJSONString().getBytes(StandardCharsets.UTF_8));}
                    int status=c.getResponseCode();JSONObject response=new JSONObject();response.put("httpStatus",status);
                    InputStream stream=status>=400?c.getErrorStream():c.getInputStream();ByteArrayOutputStream bytes=new ByteArrayOutputStream();
                    if(stream!=null)try(InputStream in=stream){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){bytes.write(b,0,n);if(bytes.size()>2000000)throw new IOException("Oversized response");}}
                    String raw=new String(bytes.toByteArray(),StandardCharsets.UTF_8).replace(key,"[redacted]");response.put("rawResponse",raw);
                    try{response.put("response",JSON.parseObject(raw));}catch(RuntimeException e){response.put("parseError","Invalid JSON object");}return response;
                }finally{c.disconnect();}
            });
            audit.putAll(f.get(timeout,TimeUnit.MILLISECONDS));
            JSONObject body=audit.getJSONObject("response"),usage=body==null?null:body.getJSONObject("usage");
            if(usage!=null){Long tokens=usage.getLong("total_tokens");if(tokens==null){String input=usage.containsKey("prompt_tokens")?"prompt_tokens":"input_tokens",output=usage.containsKey("completion_tokens")?"completion_tokens":"output_tokens";if(usage.containsKey(input)&&usage.containsKey(output))tokens=usage.getLongValue(input)+usage.getLongValue(output);}if(tokens!=null&&tokens>=0)audit.put("totalTokens",tokens);}
            if(audit.getIntValue("httpStatus")<200||audit.getIntValue("httpStatus")>=300)throw new IOException("HTTP "+audit.getIntValue("httpStatus"));
            if(body==null)throw new IOException("Invalid response JSON");audit.put("actualModel",body.getString("model"));audit.put("status","success");
        }catch(Exception e){String message=e.getClass().getSimpleName()+": "+e.getMessage();audit.put("error",key==null||key.isEmpty()?message:message.replace(key,"[redacted]"));}
        finally{if(pool!=null)pool.shutdownNow();if(active.get()!=null)active.get().disconnect();audit.put("responseMillis",(System.nanoTime()-start)/1e6);}
        return audit;
    }
    public static JSONObject generate(GuidanceOptions options,JSONObject task){
        JSONObject req=new JSONObject();req.put("model",options.generator.model);req.put("temperature",options.generator.temperature);req.put("stream",false);req.put("response_format",Collections.singletonMap("type","json_object"));
        JSONArray messages=new JSONArray();JSONObject system=new JSONObject();system.put("role","system");system.put("content",LegacyAblationProtocol.generationInstructions());messages.add(system);
        JSONObject user=new JSONObject();user.put("role","user");user.put("content",task.toJSONString());messages.add(user);req.put("messages",messages);
        String url=options.generator.baseUrl.replaceAll("/+$","")+"/chat/completions";
        JSONObject a=exchange(url,System.getenv(options.generator.apiKeyEnv),options.generator.timeoutMillis,req);
        return decodeGeneration(a,options);
    }
    public static JSONObject decodeGeneration(JSONObject a,GuidanceOptions options){
        if("success".equals(a.getString("status")))try {
            JSONObject body=a.getJSONObject("response");if(!options.generator.model.equals(body.getString("model")))throw new IOException("Unexpected model version");
            JSONArray choices=body.getJSONArray("choices");if(choices==null||choices.size()!=1)throw new IOException("Expected one completion");
            JSONObject choice=choices.getJSONObject(0);if(!"stop".equals(choice.getString("finish_reason")))throw new IOException("Truncated or unsuccessful completion");
            JSONObject parsed=JSON.parseObject(choice.getJSONObject("message").getString("content"),JSONReader.Feature.DuplicateKeyValueAsArray);
            JSONArray candidates=parsed==null?null:parsed.getJSONArray("candidates");if(candidates==null||candidates.isEmpty()||candidates.size()>options.candidatesPerTask)throw new IOException("Invalid or empty candidates");a.put("candidates",candidates);
        }catch(Exception e){a.put("status","failed");a.put("error",e.getClass().getSimpleName()+": invalid completion content");}
        return a;
    }
    public static final String CHOICE_PROMPT_VERSION="candidate-consistency-choice-v2-compact";
    public static JSONObject choiceRequest(JSONObject evidence,String model){
        if(LegacyAblationProtocol.enabled())return LegacyAblationProtocol.choiceRequest(evidence,model);
        JSONObject q=new JSONObject();q.put("type","choice");q.put("instructions","IFN is minimized; CHD, CMQ, Instability and UCM are maximized. All normalizedLoss values are lower-is-better. Here Instability is the all-service mean provided/(provided+required), isolated=0, not an external definition. Select one remaining candidate or KEEP using actual five-metric trade-offs and use-case/operation and operation/entity consistency evidence. Cross-service access is not automatically inconsistent. Do not invent behavior or require co-location. Equal consistency evidence is non-discriminative. Selection does not guarantee improvement or retention. Return the offered Choice only.");
        JSONObject criteria=new JSONObject();for(String id:new TreeSet<>(evidence.getJSONObject("choices").keySet()))criteria.put(id,"KEEP".equals(id)?"Stop selecting further candidates":"Candidate "+id+"; see state.candidates");
        q.put("criteria",criteria);JSONObject req=new JSONObject();req.put("model",model);req.put("state",CompactGuidanceChoice.pack(evidence));req.put("questions",Collections.singletonMap("configuration",q));return req;
    }
    public static JSONObject choose(ExperimentConfig.JevOptions jev,JSONObject evidence){
        JSONObject req=choiceRequest(evidence,jev.model);
        int bytes=req.toJSONString().getBytes(StandardCharsets.UTF_8).length;
        if((!LegacyAblationProtocol.enabled()||LegacyAblationProtocol.compactChoice())&&(jev.guidanceMaxRequestBytes<1024||bytes>jev.guidanceMaxRequestBytes)){JSONObject failed=new JSONObject();failed.put("status","failed");failed.put("attempted",false);failed.put("totalTokens",null);failed.put("request",req);failed.put("requestBytes",bytes);failed.put("requestByteLimit",jev.guidanceMaxRequestBytes);failed.put("error","LOCAL_REQUEST_BUDGET_EXCEEDED: full evidence retained locally; no truncation or network request");return failed;}
        if(jev.model==null||jev.model.trim().isEmpty()||jev.model.toLowerCase(Locale.ROOT).contains("latest")){JSONObject failed=new JSONObject();failed.put("status","failed");failed.put("attempted",false);failed.put("totalTokens",null);failed.put("request",req);failed.put("error","A fixed JEV model is required");return failed;}
        JSONObject a=exchange(jev.endpoint,System.getenv("TYPESAFE_API_KEY"),jev.timeoutMillis,req);
        a.put("requestBytes",bytes);a.put("requestByteLimit",jev.guidanceMaxRequestBytes);
        if("success".equals(a.getString("status")))try{
            JSONObject body=a.getJSONObject("response"),answer=body.getJSONObject("answers").getJSONObject("configuration");
            if(jev.model==null||jev.model.contains("latest")||!jev.model.equals(body.getString("model"))||!"choice".equals(answer.getString("type"))||!evidence.getJSONObject("choices").containsKey(answer.getString("choice")))throw new IOException("Invalid Choice");
            a.put("choice",answer.getString("choice"));a.put("confidence",answer.get("confidence"));a.put("probabilities",answer.get("probabilities"));
        }catch(Exception e){a.put("status","failed");a.put("error","Invalid JEV Choice response");}return a;
    }
}
