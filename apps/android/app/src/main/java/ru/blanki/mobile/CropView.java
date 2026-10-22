package ru.blanki.mobile;
import android.content.Context;
import android.graphics.*;
import android.view.*;

public final class CropView extends View {
    Bitmap bitmap;public float[] corners;private final Paint paint=new Paint(3);private final RectF area=new RectF();private final Path path=new Path();private int active=-1;
    public CropView(Context c,Bitmap b,float[] points){super(c);bitmap=b;corners=points;setContentDescription("Границы листа: перетащите четыре угла");setLayerType(View.LAYER_TYPE_SOFTWARE,null);}
    @Override protected void onDraw(Canvas canvas){
        super.onDraw(canvas);float scale=Math.min((float)getWidth()/bitmap.getWidth(),(float)getHeight()/bitmap.getHeight());float w=bitmap.getWidth()*scale,h=bitmap.getHeight()*scale;
        area.set((getWidth()-w)/2,(getHeight()-h)/2,(getWidth()+w)/2,(getHeight()+h)/2);canvas.drawColor(Color.rgb(28,45,42));paint.setColor(Color.WHITE);canvas.drawBitmap(bitmap,null,area,paint);
        path.reset();for(int i=0;i<4;i++){float x=area.left+corners[i*2]*w,y=area.top+corners[i*2+1]*h;if(i==0)path.moveTo(x,y);else path.lineTo(x,y);}path.close();
        paint.setStyle(Paint.Style.FILL);paint.setColor(0x2223634F);canvas.drawPath(path,paint);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(4);paint.setColor(0xFFFFD348);canvas.drawPath(path,paint);paint.setStyle(Paint.Style.FILL);
        for(int i=0;i<4;i++){float x=area.left+corners[i*2]*w,y=area.top+corners[i*2+1]*h;paint.setColor(0xFFFFD348);canvas.drawCircle(x,y,14*getResources().getDisplayMetrics().density,paint);paint.setColor(0xFF183D32);paint.setTextSize(14*getResources().getDisplayMetrics().scaledDensity);paint.setTextAlign(Paint.Align.CENTER);canvas.drawText(""+(i+1),x,y+5*getResources().getDisplayMetrics().density,paint);}
    }
    @Override public boolean onTouchEvent(MotionEvent e){
        if(e.getAction()==MotionEvent.ACTION_DOWN){float best=90*getResources().getDisplayMetrics().density;for(int i=0;i<4;i++){float d=(float)Math.hypot(e.getX()-(area.left+corners[2*i]*area.width()),e.getY()-(area.top+corners[2*i+1]*area.height()));if(d<best){best=d;active=i;}}if(active<0)return false;getParent().requestDisallowInterceptTouchEvent(true);}
        if(active>=0){corners[2*active]=Math.max(0,Math.min(1,(e.getX()-area.left)/area.width()));corners[2*active+1]=Math.max(0,Math.min(1,(e.getY()-area.top)/area.height()));invalidate();}
        if(e.getAction()==MotionEvent.ACTION_UP||e.getAction()==MotionEvent.ACTION_CANCEL){active=-1;getParent().requestDisallowInterceptTouchEvent(false);performClick();}return true;
    }
    @Override public boolean performClick(){super.performClick();return true;}
}
