package tuning;
import com.alibaba.fastjson2.*;
import Evaluation.PaperMetrics;
import java.nio.file.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import static org.junit.jupiter.api.Assertions.*;

class LegacyAblationProtocolTest {
    @TempDir Path temp;
    @AfterEach void reset(){LegacyAblationProtocol.reset();}
    Path policy()throws Exception{
        JSONObject p=new JSONObject();p.put("protocolVersion",LegacyAblationProtocol.VERSION);p.put("metricVersion",LegacyAblationProtocol.METRICS);p.put("inputHash",LegacyAblationProtocol.INPUT);
        p.put("generationInstructions","legacy generator isolated service=1");p.put("choiceInstructions","legacy choice isolated=1");p.put("onlineInstructions","legacy online");p.put("choicePromptVersion","candidate-consistency-choice-v1");p.put("metricDefinitions",new JSONArray());Path f=temp.resolve("protocol.json");FilesIO.write(f,p);return f;
    }
    @Test void legacyIsExplicitAndNeverChangesDefaultsAfterReset()throws Exception{
        assertFalse(LegacyAblationProtocol.enabled());assertEquals(0,LegacyAblationProtocol.isolatedScore());assertEquals(PaperMetrics.VERSION,new RunResult().metricVersion);
        LegacyAblationProtocol.activate(policy());assertEquals(1,LegacyAblationProtocol.isolatedScore());assertEquals("paper-ieee-eq5-21-v1",new RunResult().metricVersion);
        PaperMetricsTest fixture=new PaperMetricsTest();fixture.model(3,3);fixture.initialize();java.util.ArrayList<java.util.ArrayList<Integer>> g=fixture.groups(new int[]{0,1,2});assertEquals(1,PaperMetrics.evaluate(g,g)[3]);
        LegacyAblationProtocol.reset();fixture.initialize();assertEquals(0,PaperMetrics.evaluate(g,g)[3]);assertEquals(PaperMetrics.VERSION,new RunResult().metricVersion);assertEquals(GuidanceClients.CHOICE_PROMPT_VERSION,LegacyAblationProtocol.choiceVersion());
    }
    @Test void legacyChoicePreservesFullStateAndFullCriteria()throws Exception{
        LegacyAblationProtocol.activate(policy());JSONObject evidence=JSON.parseObject("{\"choices\":{\"candidate-1\":{\"solution\":{\"chromosome\":[0,0]}}},\"dependencySnapshotHash\":\"abc\"}");
        JSONObject request=GuidanceClients.choiceRequest(evidence,"jev-1.14.0");assertEquals(evidence,request.getJSONObject("state"));assertEquals(evidence.getJSONObject("choices"),request.getJSONObject("questions").getJSONObject("configuration").getJSONObject("criteria"));assertEquals("legacy online",OnlineJevClient.request(new JSONObject(),"jev-1.14.0").getJSONObject("questions").getJSONObject("configuration").getString("instructions"));
    }
    @Test void wrongInputCannotActivateLegacy()throws Exception{
        Path file=policy();JSONObject p=FilesIO.object(file);p.put("inputHash","wrong");FilesIO.write(file,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(file));assertFalse(LegacyAblationProtocol.enabled());
    }
    @Test void libraryKeepsV2ZeroAndRequiresItsOwnC3Protocol()throws Exception{
        Path f=policy();JSONObject p=FilesIO.object(f);p.put("protocolVersion",LegacyAblationProtocol.LIBRARY_VERSION);p.put("inputHash",LegacyAblationProtocol.LIBRARY_INPUT);p.put("metricVersion",PaperMetrics.VERSION);p.put("selectedConfig","C3");FilesIO.write(f,p);LegacyAblationProtocol.activate(f);
        assertEquals(0,LegacyAblationProtocol.isolatedScore());assertEquals("C3",LegacyAblationProtocol.selectedConfig());assertEquals(PaperMetrics.VERSION,new RunResult().metricVersion);
        PaperMetricsTest fixture=new PaperMetricsTest();fixture.model(3,3);fixture.initialize();java.util.ArrayList<java.util.ArrayList<Integer>> g=fixture.groups(new int[]{0,1,2});assertEquals(0,PaperMetrics.evaluate(g,g)[3]);
        LegacyAblationProtocol.activate(policy());fixture.initialize();assertEquals(1,PaperMetrics.evaluate(g,g)[3]);LegacyAblationProtocol.reset();fixture.initialize();assertEquals(0,PaperMetrics.evaluate(g,g)[3]);
        p.put("selectedConfig","C5");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
    }
    @Test void historicalCommentBehaviorIsConfinedToExplicitLibraryMode()throws Exception{
        Path input=temp.resolve("comments.remodel");Files.write(input,"DomainModel X {\nEntity First {\n}\nEntity Second {\n}\n}\nContract X::run() {\nx:First\n/* historical reference Second */\n}\n".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        assertEquals(java.util.Collections.singleton("First"),GA.remodelparse.getOPstoEntity(input.toString()).get("run"));
        Path f=policy();JSONObject p=FilesIO.object(f);p.put("protocolVersion",LegacyAblationProtocol.LIBRARY_VERSION);p.put("inputHash",LegacyAblationProtocol.LIBRARY_INPUT);p.put("metricVersion",PaperMetrics.VERSION);p.put("selectedConfig","C3");p.put("historicalParser","raw-comment-reader-v1");FilesIO.write(f,p);LegacyAblationProtocol.activate(f);
        assertEquals(new java.util.HashSet<>(java.util.Arrays.asList("First","Second")),GA.remodelparse.getOPstoEntity(input.toString()).get("run"));
        LegacyAblationProtocol.reset();assertEquals(java.util.Collections.singleton("First"),GA.remodelparse.getOPstoEntity(input.toString()).get("run"));
    }
    @Test void springRequiresC3AndCompactProtocol()throws Exception{
        Path f=policy();JSONObject p=FilesIO.object(f);p.put("protocolVersion",LegacyAblationProtocol.SPRING_VERSION);p.put("inputHash",LegacyAblationProtocol.SPRING_INPUT);p.put("metricVersion",PaperMetrics.VERSION);p.put("selectedConfig","C3");p.put("historicalParser","filtered-comment-reader-v1");p.put("choicePromptVersion",GuidanceClients.CHOICE_PROMPT_VERSION);FilesIO.write(f,p);LegacyAblationProtocol.activate(f);
        assertEquals("C3",LegacyAblationProtocol.selectedConfig());assertEquals(0,LegacyAblationProtocol.isolatedScore());assertTrue(LegacyAblationProtocol.compactChoice());assertFalse(LegacyAblationProtocol.historicalRawComments());
        LegacyAblationProtocol.reset();p.put("choicePromptVersion","candidate-consistency-choice-v1");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
        p.put("choicePromptVersion",GuidanceClients.CHOICE_PROMPT_VERSION);p.put("selectedConfig","C5");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
    }
    @Test void lightRequiresC3AndKeepsFilteredParserUnlikeHistoricalLibrary()throws Exception{
        Path f=policy();JSONObject p=FilesIO.object(f);p.put("protocolVersion",LegacyAblationProtocol.LIGHT_VERSION);p.put("inputHash",LegacyAblationProtocol.LIGHT_INPUT);p.put("metricVersion",PaperMetrics.VERSION);p.put("selectedConfig","C3");p.put("historicalParser","filtered-comment-reader-v1");FilesIO.write(f,p);LegacyAblationProtocol.activate(f);
        assertEquals("C3",LegacyAblationProtocol.selectedConfig());assertEquals(0,LegacyAblationProtocol.isolatedScore());assertFalse(LegacyAblationProtocol.historicalRawComments());
        LegacyAblationProtocol.reset();p.put("inputHash",LegacyAblationProtocol.LIBRARY_INPUT);FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
        p.put("inputHash",LegacyAblationProtocol.LIGHT_INPUT);p.put("selectedConfig","C5");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
        p.put("selectedConfig","C3");p.put("historicalParser","raw-comment-reader-v1");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
    }
    @Test void piggyRequiresItsOwnC5InputAndFilteredParser()throws Exception{
        Path f=policy();JSONObject p=FilesIO.object(f);p.put("protocolVersion",LegacyAblationProtocol.PIGGY_VERSION);p.put("inputHash",LegacyAblationProtocol.PIGGY_INPUT);p.put("metricVersion",PaperMetrics.VERSION);p.put("selectedConfig","C5");p.put("historicalParser","filtered-comment-reader-v1");FilesIO.write(f,p);LegacyAblationProtocol.activate(f);
        assertEquals("C5",LegacyAblationProtocol.selectedConfig());assertEquals(0,LegacyAblationProtocol.isolatedScore());assertFalse(LegacyAblationProtocol.historicalRawComments());
        LegacyAblationProtocol.reset();p.put("inputHash",LegacyAblationProtocol.LOAN_INPUT);FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
        p.put("inputHash",LegacyAblationProtocol.PIGGY_INPUT);p.put("selectedConfig","C0");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
        p.put("selectedConfig","C5");p.put("historicalParser","raw-comment-reader-v1");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
    }
    @Test void taxiRequiresItsOwnC5InputAndFilteredParser()throws Exception{
        Path f=policy();JSONObject p=FilesIO.object(f);p.put("protocolVersion",LegacyAblationProtocol.TAXI_VERSION);p.put("inputHash",LegacyAblationProtocol.TAXI_INPUT);p.put("metricVersion",PaperMetrics.VERSION);p.put("selectedConfig","C5");p.put("historicalParser","filtered-comment-reader-v1");FilesIO.write(f,p);LegacyAblationProtocol.activate(f);
        assertEquals("C5",LegacyAblationProtocol.selectedConfig());assertEquals(0,LegacyAblationProtocol.isolatedScore());assertFalse(LegacyAblationProtocol.historicalRawComments());
        LegacyAblationProtocol.reset();p.put("inputHash",LegacyAblationProtocol.LOAN_INPUT);FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
        p.put("inputHash",LegacyAblationProtocol.TAXI_INPUT);p.put("selectedConfig","C0");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
        p.put("selectedConfig","C5");p.put("historicalParser","raw-comment-reader-v1");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
    }
    @Test void loanRequiresItsOwnC5InputAndFilteredParser()throws Exception{
        Path f=policy();JSONObject p=FilesIO.object(f);p.put("protocolVersion",LegacyAblationProtocol.LOAN_VERSION);p.put("inputHash",LegacyAblationProtocol.LOAN_INPUT);p.put("metricVersion",PaperMetrics.VERSION);p.put("selectedConfig","C5");p.put("historicalParser","filtered-comment-reader-v1");FilesIO.write(f,p);LegacyAblationProtocol.activate(f);
        assertEquals("C5",LegacyAblationProtocol.selectedConfig());assertEquals(0,LegacyAblationProtocol.isolatedScore());assertFalse(LegacyAblationProtocol.historicalRawComments());
        LegacyAblationProtocol.reset();p.put("selectedConfig","C0");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
        p.put("selectedConfig","C5");p.put("historicalParser","raw-comment-reader-v1");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
    }
    @Test void atmUsesC0ZeroIsolatedAndFilteredParser()throws Exception{
        Path f=policy();JSONObject p=FilesIO.object(f);p.put("protocolVersion",LegacyAblationProtocol.ATM_VERSION);p.put("inputHash",LegacyAblationProtocol.ATM_INPUT);p.put("metricVersion",PaperMetrics.VERSION);p.put("selectedConfig","C0");p.put("historicalParser","filtered-comment-reader-v1");FilesIO.write(f,p);LegacyAblationProtocol.activate(f);
        assertEquals("C0",LegacyAblationProtocol.selectedConfig());assertEquals(0,LegacyAblationProtocol.isolatedScore());assertFalse(LegacyAblationProtocol.historicalRawComments());assertEquals(LegacyAblationProtocol.ATM_INPUT,LegacyAblationProtocol.inputHash());
        LegacyAblationProtocol.reset();p.put("historicalParser","raw-comment-reader-v1");FilesIO.write(f,p);assertThrows(IllegalArgumentException.class,()->LegacyAblationProtocol.activate(f));
    }
}
