package ru.blanki.mobile;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import androidx.exifinterface.media.ExifInterface;
import java.io.*;
import java.util.*;
import org.opencv.android.Utils;
import org.opencv.core.*;
import org.opencv.imgproc.Imgproc;

public final class ImageTools {
    public static Bitmap load(File file,int max)throws IOException{
        BitmapFactory.Options o=new BitmapFactory.Options();o.inJustDecodeBounds=true;BitmapFactory.decodeFile(file.toString(),o);
        if(o.outWidth<1||o.outHeight<1||(long)o.outWidth*o.outHeight>100_000_000)throw new IOException("Не удалось прочитать изображение или оно слишком большое");
        o.inSampleSize=1;while(Math.max(o.outWidth,o.outHeight)/o.inSampleSize>max*2)o.inSampleSize*=2;
        o.inJustDecodeBounds=false;o.inPreferredConfig=Bitmap.Config.ARGB_8888;Bitmap b=BitmapFactory.decodeFile(file.toString(),o);
        if(b==null)throw new IOException("Формат изображения не поддерживается");
        try{
            int orientation=new ExifInterface(file.toString()).getAttributeInt(ExifInterface.TAG_ORIENTATION,1);Matrix m=new Matrix();
            switch(orientation){case 2:m.setScale(-1,1);break;case 3:m.setRotate(180);break;case 4:m.setScale(1,-1);break;case 5:m.setRotate(90);m.postScale(-1,1);break;case 6:m.setRotate(90);break;case 7:m.setRotate(270);m.postScale(-1,1);break;case 8:m.setRotate(270);break;}
            if(!m.isIdentity()){Bitmap r=Bitmap.createBitmap(b,0,0,b.getWidth(),b.getHeight(),m,true);if(r!=b)b.recycle();b=r;}
        }catch(IOException ignored){}
        float scale=Math.min(1f,(float)max/Math.max(b.getWidth(),b.getHeight()));if(scale<1){Bitmap r=Bitmap.createScaledBitmap(b,Math.round(b.getWidth()*scale),Math.round(b.getHeight()*scale),true);b.recycle();b=r;}return b;
    }
    public static void save(Bitmap b,File f)throws IOException{
        android.util.AtomicFile target=new android.util.AtomicFile(f);FileOutputStream out=null;
        try{out=target.startWrite();if(!b.compress(Bitmap.CompressFormat.JPEG,95,out))throw new IOException("Не удалось сохранить скан");target.finishWrite(out);}
        catch(IOException|RuntimeException e){if(out!=null)target.failWrite(out);throw e;}
    }
    public static Bitmap rotate(Bitmap b){Matrix m=new Matrix();m.postRotate(90);return Bitmap.createBitmap(b,0,0,b.getWidth(),b.getHeight(),m,true);}
    public static float[] detect(Bitmap bitmap){
        Bitmap small=Bitmap.createScaledBitmap(bitmap,Math.max(1,bitmap.getWidth()*900/Math.max(bitmap.getWidth(),bitmap.getHeight())),Math.max(1,bitmap.getHeight()*900/Math.max(bitmap.getWidth(),bitmap.getHeight())),true);
        Mat m=new Mat(),g=new Mat(),edges=new Mat(),hier=new Mat();List<MatOfPoint> contours=new ArrayList<>();float[] answer={.02f,.02f,.98f,.02f,.98f,.98f,.02f,.98f};
        try{
            Utils.bitmapToMat(small,m);Imgproc.cvtColor(m,g,Imgproc.COLOR_RGBA2GRAY);Imgproc.GaussianBlur(g,g,new Size(5,5),0);Imgproc.Canny(g,edges,50,150);
            Imgproc.findContours(edges,contours,hier,Imgproc.RETR_LIST,Imgproc.CHAIN_APPROX_SIMPLE);double best=m.rows()*m.cols()*.25;
            for(MatOfPoint c:contours){double a=Imgproc.contourArea(c);if(a<=best)continue;MatOfPoint2f pts=new MatOfPoint2f(c.toArray()),approx=new MatOfPoint2f();
                Imgproc.approxPolyDP(pts,approx,.02*Imgproc.arcLength(pts,true),true);Point[] p=approx.toArray();
                if(p.length==4){Point[] ordered=order(p);float[] candidate=new float[8];for(int i=0;i<4;i++){candidate[2*i]=(float)(ordered[i].x/m.cols());candidate[2*i+1]=(float)(ordered[i].y/m.rows());}
                    if(valid(candidate)){answer=candidate;best=a;}}
                pts.release();approx.release();
            }
        }finally{for(MatOfPoint c:contours)c.release();m.release();g.release();edges.release();hier.release();if(small!=bitmap)small.recycle();}return answer;
    }
    static Point[] order(Point[] p){Arrays.sort(p,Comparator.comparingDouble(x->x.y));Point[] top={p[0],p[1]},bottom={p[2],p[3]};Arrays.sort(top,Comparator.comparingDouble(x->x.x));Arrays.sort(bottom,Comparator.comparingDouble(x->x.x));return new Point[]{top[0],top[1],bottom[1],bottom[0]};}
    public static boolean valid(float[] q){
        double sign=0,area=0;for(int i=0;i<4;i++){int a=i*2,b=((i+1)%4)*2,c=((i+2)%4)*2;double cross=(q[b]-q[a])*(q[c+1]-q[b+1])-(q[b+1]-q[a+1])*(q[c]-q[b]);if(Math.abs(cross)<.003||i>0&&cross*sign<0)return false;sign=cross;area+=q[a]*q[b+1]-q[b]*q[a+1];}return Math.abs(area)>.08;
    }
    public static Bitmap crop(Bitmap b,float[] q,int filter,int contrast)throws IOException{
        if(!valid(q))throw new IOException("Углы пересекаются или область слишком мала");
        Point[] p=new Point[4];for(int i=0;i<4;i++)p[i]=new Point(q[i*2]*b.getWidth(),q[i*2+1]*b.getHeight());
        int w=(int)Math.max(distance(p[0],p[1]),distance(p[3],p[2])),h=(int)Math.max(distance(p[0],p[3]),distance(p[1],p[2]));
        if(w<300||h<300)throw new IOException("Слишком маленький фрагмент");
        Mat src=new Mat(),dst=new Mat(),rgb=new Mat();MatOfPoint2f from=new MatOfPoint2f(p),to=new MatOfPoint2f(new Point(0,0),new Point(w,0),new Point(w,h),new Point(0,h));Mat matrix=Imgproc.getPerspectiveTransform(from,to);
        try{
            Utils.bitmapToMat(b,src);Imgproc.warpPerspective(src,dst,matrix,new Size(w,h),Imgproc.INTER_CUBIC,Core.BORDER_CONSTANT,new Scalar(255,255,255,255));
            if(filter>0){Imgproc.cvtColor(dst,rgb,Imgproc.COLOR_RGBA2GRAY);if(filter==2)Imgproc.adaptiveThreshold(rgb,rgb,255,Imgproc.ADAPTIVE_THRESH_GAUSSIAN_C,Imgproc.THRESH_BINARY,35,15);Imgproc.cvtColor(rgb,dst,Imgproc.COLOR_GRAY2RGBA);}
            double alpha=.7+contrast/100.0;dst.convertTo(dst,-1,alpha,128*(1-alpha));Bitmap out=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);Utils.matToBitmap(dst,out);return out;
        }finally{src.release();dst.release();rgb.release();from.release();to.release();matrix.release();}
    }
    static double distance(Point a,Point b){return Math.hypot(a.x-b.x,a.y-b.y);}
}
