"""Train, evaluate and run a real YOLO detector for collected NT$1/5 coins."""
import argparse
import json
import os
from pathlib import Path
import time

BASE=Path(__file__).resolve().parent
os.environ.setdefault('YOLO_CONFIG_DIR', str(BASE/'.build/yolo_config'))
os.environ.setdefault('YOLO_AUTOINSTALL','false')
os.environ.setdefault('OMP_NUM_THREADS','6')
os.environ.setdefault('MKL_NUM_THREADS','6')


def load(weights):
    import torch
    from ultralytics import YOLO, settings
    settings.update({'sync':False})
    torch.set_num_threads(6)
    return YOLO(str(weights))


def evaluate(model, args):
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    output=BASE/'output/coin_yolo/evaluation'
    output.mkdir(parents=True,exist_ok=True)
    records=json.loads((BASE/'coin_dataset/yolo_1_5/annotations.json').read_text(encoding='utf-8'))
    records=[r for r in records if r['split']=='val']
    counts={name:{'images':0,'correct':0,'wrong_class':0,'missed':0,'extra_boxes':0} for name in ('coin_1','coin_5')}
    thumbnails=[]
    for record in records:
        image=cv2.imdecode(np.fromfile(BASE/record['source'],np.uint8),cv2.IMREAD_COLOR)
        result=model.predict(image,imgsz=args.imgsz,conf=args.conf,device='cpu',verbose=False)[0]
        boxes=result.boxes.xyxy.cpu().numpy()
        classes=result.boxes.cls.cpu().numpy().astype(int)
        target=np.array(record['box'])
        overlaps=[]
        for box in boxes:
            inter=np.maximum(0,np.minimum(box[2:],target[2:])-np.maximum(box[:2],target[:2])).prod()
            union=(box[2:]-box[:2]).prod()+(target[2:]-target[:2]).prod()-inter
            overlaps.append(float(inter/union))
        best=int(np.argmax(overlaps)) if overlaps else -1
        matched=best>=0 and overlaps[best]>=.5
        status='missed' if not matched else 'correct' if classes[best]==record['class_id'] else 'wrong_class'
        row=counts[record['name']]
        row['images']+=1; row[status]+=1
        row['extra_boxes']+=max(0,len(boxes)-int(matched))
        record['prediction_status']=status
        record['detections']=[{'xyxy':b.tolist(),'class_id':int(c),'confidence':float(s)} for b,c,s in zip(boxes,classes,result.boxes.conf.cpu().numpy())]
        thumb=Image.fromarray(cv2.cvtColor(result.plot(),cv2.COLOR_BGR2RGB))
        thumb.thumbnail((316,178))
        thumbnails.append((thumb,f"{record['name']} {status}"))
    for page,start in enumerate(range(0,len(thumbnails),24)):
        sheet=Image.new('RGB',(1280,1230),'white'); draw=ImageDraw.Draw(sheet)
        for i,(thumb,caption) in enumerate(thumbnails[start:start+24]):
            x,y=i%4*320,i//4*205
            sheet.paste(thumb,(x,y)); draw.text((x+2,y+179),caption,fill='black')
        sheet.save(output/f'predictions_{page:02d}.jpg')
    report={'weights':str(args.weights),'confidence_threshold':args.conf,'iou_threshold':.5,
            'scope':'Validation only; same capture environment; no independent test set. Assisted box annotations.',
            'counts':counts,'images':records}
    (output/'detections.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(counts,indent=2))


def live(model,args):
    import cv2
    import numpy as np
    from foot_live import LiveStream
    stream=LiveStream(args.url)
    title='YOLO coin detector - NT$1 / NT$5 - Q to exit'
    last_stamp=None
    started=time.monotonic()
    frames=0
    if not args.probe_seconds:
        cv2.namedWindow(title,cv2.WINDOW_NORMAL); cv2.resizeWindow(title,1000,620)
    try:
        while True:
            try:
                frame,stamp=stream.snapshot()
            except ValueError:
                frame=None
            if frame is not None and stamp!=last_stamp:
                result=model.predict(frame,imgsz=args.imgsz,conf=args.conf,device='cpu',verbose=False)[0]
                rendered=result.plot()
                last_stamp=stamp; frames+=1
                if args.probe_seconds:
                    folder=BASE/'output/coin_yolo/live_probe'; folder.mkdir(parents=True,exist_ok=True)
                    ok,encoded=cv2.imencode('.png',rendered)
                    if ok:
                        (folder/'prediction.png').write_bytes(encoded.tobytes())
                    (folder/'detections.json').write_text(result.to_json(),encoding='utf-8')
                else:
                    cv2.imshow(title,rendered)
            elif frame is None and not args.probe_seconds:
                blank=np.zeros((720,1280,3),np.uint8)
                cv2.putText(blank,'Waiting for fresh RTSP frame - check Wi-Fi / URL',(20,45),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,200,255),2)
                cv2.imshow(title,blank)
            if args.probe_seconds:
                if time.monotonic()-started>=args.probe_seconds:
                    print(json.dumps({'fresh_frames_processed':frames}))
                    break
                time.sleep(.05)
            elif cv2.waitKey(20)&255 in (27,ord('q')) or cv2.getWindowProperty(title,cv2.WND_PROP_VISIBLE)<1:
                break
    finally:
        stream.close()
        if not args.probe_seconds:
            cv2.destroyAllWindows()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['train','evaluate','live','image'])
    parser.add_argument('--weights',type=Path,default=BASE/'output/coin_yolo/train/weights/best.pt')
    parser.add_argument('--data',type=Path,default=BASE/'coin_dataset/yolo_1_5/data.yaml',
                        help='YOLO data.yaml used by train')
    parser.add_argument('--project',type=Path,default=BASE/'output/coin_yolo',
                        help='folder containing this training run')
    parser.add_argument('--name',default='train',help='training-run name inside --project')
    parser.add_argument('--epochs',type=int,default=40)
    parser.add_argument('--imgsz',type=int,default=416)
    parser.add_argument('--conf',type=float,default=.5)
    parser.add_argument('--url')
    parser.add_argument('--image',type=Path)
    parser.add_argument('--probe-seconds',type=float,default=0)
    args=parser.parse_args()
    if args.mode=='train':
        model=load(BASE/'yolov8n.pt')
        # Real pretrained YOLO weights; the forward pass verifies the runtime first.
        import numpy as np
        model.predict(np.zeros((416,416,3),np.uint8),imgsz=args.imgsz,device='cpu',verbose=False)
        result=model.train(data=str(args.data),epochs=args.epochs,
                          imgsz=args.imgsz,batch=8,device='cpu',workers=0,freeze=10,
                          optimizer='AdamW',lr0=.001,patience=12,seed=42,deterministic=True,
                          degrees=30,translate=.1,scale=.3,hsv_h=.01,hsv_s=.3,hsv_v=.3,
                          mosaic=.5,close_mosaic=5,amp=False,cache=False,
                          project=str(args.project),name=args.name,exist_ok=False,
                          plots=True,save=True)
        folder=Path(model.trainer.save_dir)
        (folder/'validation_metrics.json').write_text(json.dumps(result.results_dict,indent=2),encoding='utf-8')
        (BASE/'output/coin_yolo/latest_weights.txt').write_text(str(folder/'weights/best.pt'),encoding='utf-8')
        print(f'FINAL_WEIGHTS={folder / "weights/best.pt"}')
    else:
        if not args.weights.exists():
            parser.error(f'Weights not found: {args.weights}')
        model=load(args.weights)
        if args.mode=='evaluate':
            evaluate(model,args)
        elif args.mode=='live':
            if not args.url:
                parser.error('--url is required')
            live(model,args)
        else:
            if not args.image:
                parser.error('--image is required')
            model.predict(str(args.image),imgsz=args.imgsz,conf=args.conf,device='cpu',
                          save=True,project=str(BASE/'output/coin_yolo'),name='image_predictions')


if __name__=='__main__':
    main()
