package ru.blanki.mobile;

import android.content.Context;
import java.io.*;
import java.nio.*;
import java.util.*;
import org.json.*;
import org.opencv.core.*;
import org.opencv.imgcodecs.Imgcodecs;
import org.opencv.imgproc.Imgproc;
import ai.onnxruntime.*;

public final class Ocr implements AutoCloseable {
    final OrtEnvironment env=OrtEnvironment.getEnvironment();final OrtSession session;final JSONArray alphabet;final JSONObject forms;
    double lastConfidence=1;
    public interface Progress {void step(String text);}
    static byte[] asset(Context c,String name)throws IOException{try(InputStream in=c.getAssets().open(name);ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[65536];int r;while((r=in.read(b))!=-1)out.write(b,0,r);return out.toByteArray();}}
    public Ocr(Context c)throws Exception{
        OrtSession.SessionOptions options=new OrtSession.SessionOptions();options.setIntraOpNumThreads(2);options.setInterOpNumThreads(1);
        try{session=env.createSession(asset(c,"recognizer.onnx"),options);}finally{options.close();}
        alphabet=new JSONArray(new String(asset(c,"alphabet.json"),java.nio.charset.StandardCharsets.UTF_8));forms=new JSONObject(new String(asset(c,"forms.json"),java.nio.charset.StandardCharsets.UTF_8));
    }
    public String modelText(Mat gray)throws Exception{
        int contentWidth=Math.max(1,Math.min(1600,(int)Math.ceil(48.0*gray.cols()/gray.rows()))),width=Math.max(160,contentWidth);Mat resize=new Mat();
        try{
            Imgproc.resize(gray,resize,new Size(contentWidth,48));byte[] pixels=new byte[contentWidth*48];resize.get(0,0,pixels);float[] input=new float[3*width*48];
            for(int y=0;y<48;y++)for(int x=0;x<contentWidth;x++){float value=(pixels[y*contentWidth+x]&255)/127.5f-1;for(int channel=0;channel<3;channel++)input[channel*width*48+y*width+x]=value;}
            try(OnnxTensor tensor=OnnxTensor.createTensor(env,FloatBuffer.wrap(input),new long[]{1,3,48,width});OrtSession.Result result=session.run(Collections.singletonMap(session.getInputNames().iterator().next(),tensor))){
                float[][] logits=((float[][][])result.get(0).getValue())[0];StringBuilder text=new StringBuilder();int previous=-1;
                double sum=0;int symbols=0;for(float[] row:logits){int best=0;for(int i=1;i<row.length;i++)if(row[i]>row[best])best=i;if(best!=0&&best!=previous&&best<alphabet.length()){text.append(alphabet.getString(best));sum+=row[best];symbols++;}previous=best;}lastConfidence=symbols==0?0:sum/symbols;return text.toString().trim();
            }
        }finally{resize.release();}
    }
    public Mat align(Mat image,JSONObject form,boolean ege)throws Exception{
        JSONArray size=form.getJSONArray("size"),marks=form.getJSONArray("markers");Mat g=new Mat(),ink=new Mat(),hier=new Mat();List<MatOfPoint> contours=new ArrayList<>();List<double[]> candidates=new ArrayList<>();
        try{
            Imgproc.cvtColor(image,g,Imgproc.COLOR_BGR2GRAY);Imgproc.threshold(g,ink,ege?160:180,255,Imgproc.THRESH_BINARY_INV);Imgproc.findContours(ink,contours,hier,Imgproc.RETR_EXTERNAL,Imgproc.CHAIN_APPROX_SIMPLE);
            double full=(double)image.rows()*image.cols();
            for(MatOfPoint c:contours){double a=Imgproc.contourArea(c);Rect r=Imgproc.boundingRect(c);double ratio=(double)r.width/r.height,extent=a/(r.width*r.height);
                if(ege?a/full>.0002&&a/full<.0015&&ratio>.7&&ratio<1.4&&extent>.75:a>60&&a<50000&&ratio>.66&&ratio<1.5&&extent>.45)candidates.add(new double[]{r.x+r.width/2.0,r.y+r.height/2.0,a});}
            Point[] from=new Point[4],to=new Point[4];Set<double[]> used=new HashSet<>();
            for(int i=0;i<4;i++){
                JSONArray mark=marks.getJSONArray(i);to[i]=new Point(mark.getDouble(0),mark.getDouble(1));double ex=to[i].x/size.getDouble(0),ey=to[i].y/size.getDouble(1);double[] best=null;double bestScore=Double.POSITIVE_INFINITY;
                JSONArray zone=ege?null:form.getJSONArray("zones").getJSONArray(i);
                for(double[] p:candidates){double x=p[0]/image.cols(),y=p[1]/image.rows();boolean in=ege?Math.abs(x-ex)<.065&&Math.abs(y-ey)<(i<2?.065:.055):x>=zone.getDouble(0)&&x<=zone.getDouble(2)&&y>=zone.getDouble(1)&&y<=zone.getDouble(3);if(!in)continue;double score=ege?Math.pow(x-ex,2)+Math.pow(y-ey,2):-p[2];if(score<bestScore){best=p;bestScore=score;}}
                if(best==null||!used.add(best))throw new IOException("Не найдены четыре метки. Проверьте границы, тип листа и поворот.");from[i]=new Point(best[0],best[1]);
            }
            if(Math.abs(from[0].y-from[1].y)>image.rows()*.045||Math.abs(from[2].y-from[3].y)>image.rows()*.045||from[1].x-from[0].x<image.cols()*.5||from[2].y-from[0].y<image.rows()*.55)throw new IOException("Метки не образуют правильный бланк. Исправьте границы.");
            MatOfPoint2f a=new MatOfPoint2f(from),b=new MatOfPoint2f(to);Mat matrix=Imgproc.getPerspectiveTransform(a,b),result=new Mat();
            try{Imgproc.warpPerspective(image,result,matrix,new Size(size.getInt(0),size.getInt(1)),Imgproc.INTER_CUBIC,Core.BORDER_CONSTANT,new Scalar(255,255,255));}finally{matrix.release();a.release();b.release();}return result;
        }finally{g.release();ink.release();hier.release();for(Mat c:contours)c.release();}
    }
    static Rect box(JSONArray a)throws Exception{return new Rect(a.getInt(0),a.getInt(1),a.getInt(2)-a.getInt(0),a.getInt(3)-a.getInt(1));}
    void crop(Mat sheet,JSONArray b,File folder,String name)throws Exception{Mat crop=new Mat(sheet,box(b));try{if(!Imgcodecs.imwrite(new File(folder,name).toString(),crop))throw new IOException("Не удалось сохранить фрагмент");}finally{crop.release();}}
    public String read(Mat sheet,JSONArray b,int count,boolean text)throws Exception{
        lastConfidence=1;
        Mat region=new Mat(sheet,box(b)),g=new Mat();Imgproc.cvtColor(region,g,Imgproc.COLOR_BGR2GRAY);region.release();Mat clean=new Mat(g.size(),CvType.CV_8UC1,new Scalar(255));int last=-1;
        try{
            for(int i=0;i<count;i++){
                int left=(int)Math.round(i*g.cols()/(double)count)+5,right=(int)Math.round((i+1)*g.cols()/(double)count)-5;if(right<=left||g.rows()<=12)continue;
                Rect cell=new Rect(left,6,right-left,g.rows()-12);Mat part=new Mat(g,cell),binary=new Mat(),labels=new Mat(),stats=new Mat(),centers=new Mat();
                try{
                    Imgproc.threshold(part,binary,180,255,Imgproc.THRESH_BINARY_INV);int n=Imgproc.connectedComponentsWithStats(binary,labels,stats,centers);byte[] out=new byte[part.rows()*part.cols()];Arrays.fill(out,(byte)255);int[] lab=new int[out.length];labels.get(0,0,lab);Set<Integer> keep=new HashSet<>();
                    for(int c=1;c<n;c++){double[] area=stats.get(c,Imgproc.CC_STAT_AREA),w=stats.get(c,Imgproc.CC_STAT_WIDTH),h=stats.get(c,Imgproc.CC_STAT_HEIGHT);if(area[0]>=35&&(w[0]>=10||h[0]>=10))keep.add(c);}
                    for(int k=0;k<lab.length;k++)if(keep.contains(lab[k])){out[k]=0;last=i;}
                    Mat dst=new Mat(clean,cell);dst.put(0,0,out);dst.release();
                }finally{part.release();binary.release();labels.release();stats.release();centers.release();}
            }
            if(last<0)return "";
            // Compact occupied cells; preserve punctuation shapes and remove empty trailing cells.
            List<Mat> pieces=new ArrayList<>();
            for(int i=0;i<=last;i++){
                int left=(int)Math.round(i*clean.cols()/(double)count),right=(int)Math.round((i+1)*clean.cols()/(double)count);Mat cell=new Mat(clean,new Rect(left,0,right-left,clean.rows()));Mat inv=new Mat();Core.bitwise_not(cell,inv);MatOfPoint points=new MatOfPoint();Core.findNonZero(inv,points);
                if(!points.empty()){Rect r=Imgproc.boundingRect(points);Mat part=new Mat(cell,new Rect(r.x,0,r.width,cell.rows())),padded=new Mat();Core.copyMakeBorder(part,padded,12,12,6,6,Core.BORDER_CONSTANT,new Scalar(255));pieces.add(padded);part.release();}
                points.release();inv.release();cell.release();
            }
            if(pieces.isEmpty())return "";Mat compact=new Mat();Core.hconcat(pieces,compact);String raw;
            try{raw=modelText(compact);}finally{compact.release();for(Mat p:pieces)p.release();}
            if(text){String latin="ABCEHKMOPTXY",cyr="АВСЕНКМОРТХУ";String value=raw.toUpperCase(Locale.ROOT).replace(" ","");StringBuilder result=new StringBuilder();for(char ch:value.toCharArray()){int i=latin.indexOf(ch);result.append(i>=0?cyr.charAt(i):ch);}return result.toString();}
            String value=raw.replace(" ","").replace('.',',').replace('O','0').replace('О','0').replace('I','1').replace('l','1');
            return value.matches("[0-9,\\-]+")?value:"";
        }finally{g.release();clean.release();}
    }
    public JSONObject process(File image,String profile,String kind,File folder,Progress progress)throws Exception{
        if(!Arrays.asList("oge","registration","answers").contains(kind))throw new IOException("Сначала выберите тип листа. Лист №2 проверяется вручную.");
        String layout=Profile.ege(profile)?"ege_"+(kind.equals("registration")?"registration":"answers"):profile.equals("oge_russian")?"oge_russian":"oge_math";
        Mat source=Imgcodecs.imread(image.toString()),sheet=null;if(source.empty())throw new IOException("Скан не читается");
        try{
            JSONObject form=forms.getJSONObject(layout);progress.step("Выравнивание по меткам");sheet=align(source,form,Profile.ege(profile));
            Imgcodecs.imwrite(new File(folder,"aligned.jpg").toString(),sheet);
            JSONObject answers=new JSONObject(),result=new JSONObject().put("answers",answers).put("reviewed",false).put("ocr_version","android-onnx-eslav-preview1");
            JSONArray names=form.getJSONArray("names");StringBuilder name=new StringBuilder();
            for(int i=0;i<names.length();i++){progress.step("ФИО: строка "+(i+1));crop(sheet,names.getJSONArray(i),folder,"name_"+i+".png");String s=read(sheet,names.getJSONArray(i),30,true);if(!s.isBlank()){if(name.length()>0)name.append(' ');name.append(s);}}
            if(names.length()>0)result.put("name",name.toString());
            if(form.has("region")){progress.step("Номер варианта");crop(sheet,form.getJSONArray("region"),folder,"region.png");String v=read(sheet,form.getJSONArray("region"),2,false);result.put("variant",v);result.put("variant_raw",v);}
            if(form.has("school")){crop(sheet,form.getJSONArray("school"),folder,"school.png");result.put("school",read(sheet,form.getJSONArray("school"),6,false));}
            JSONObject confidence=new JSONObject();result.put("confidence",confidence);
            JSONObject boxes=form.getJSONObject("answers");for(int t=Profile.start(profile);t<=Profile.end(profile);t++)if(boxes.has(""+t)){
                progress.step("Ответ "+t+" из "+Profile.end(profile));JSONArray b=boxes.getJSONArray(""+t);crop(sheet,b,folder,"answer_"+t+".png");answers.put(""+t,read(sheet,b,17,Profile.russian(profile)));confidence.put(""+t,lastConfidence);
            }
            if(form.has("corrections"))crop(sheet,form.getJSONArray("corrections"),folder,"corrections.png");
            return result.put("raw",new JSONObject(answers.toString())).put("recognized",true);
        }finally{source.release();if(sheet!=null)sheet.release();}
    }
    @Override public void close()throws OrtException{session.close();}
}
