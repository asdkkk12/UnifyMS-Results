import com.alibaba.fastjson2.JSON;
public class SpringLargeJsonCheck {
 public static void main(String[] args) {
  String text="a".repeat(70*1024*1024);
  try {
   String encoded=JSON.toJSONString(text,com.alibaba.fastjson2.JSONWriter.Feature.PrettyFormat,com.alibaba.fastjson2.JSONWriter.Feature.WriteNulls);
   if(!JSON.parseObject(encoded,String.class).equals(text))throw new AssertionError("Roundtrip changed text");
   System.out.println("{\"roundtrip\":true,\"input_chars\":"+text.length()+",\"output_chars\":"+encoded.length()+"}");
  } catch(OutOfMemoryError e) {
   if(args.length==0 || !args[0].equals("expect-default-limit"))throw e;
   System.out.println("{\"default_writer_size_limit_confirmed\":true}");
  }
 }
}
