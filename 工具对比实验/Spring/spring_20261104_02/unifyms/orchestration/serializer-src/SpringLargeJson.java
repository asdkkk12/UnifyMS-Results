package com.alibaba.fastjson2;
import java.lang.instrument.Instrumentation;

/** Enable the installed Fastjson2 size feature; no search/model/metric code changes. */
public class SpringLargeJson {
 public static void premain(String args,Instrumentation instrumentation) {
  JSONFactory.defaultWriterFeatures|=JSONWriter.Feature.LargeObject.mask;
 }
}
