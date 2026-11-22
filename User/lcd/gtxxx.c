/**
  ******************************************************************************
  * @file    gtxxx.c
  * @author  embedfire
  * @brief   
  ******************************************************************************
  * @attention
  *
  ******************************************************************************
  */

#include <string.h>
#include <stdio.h>
#include "bsp_lcd_tp_i2c.h"
#include "gtxxx.h"

uint8_t gt_addr_try[2] = {0x28,0xBA};
uint8_t gt_addr_use;
uint8_t gt_max_points;
uint8_t gt_id[5];


uint8_t Gt_Reg_Write(uint8_t addr,uint16_t reg,uint8_t *buffer,uint8_t size)
{     
    TP_I2C_Start();               /*发起I2C总线启动信号 */   
    TP_I2C_SendByte(GT_ADDR_WRITE(addr));  /*发送写设备地址 */ 
    if (TP_I2C_WaitAck() != 0)    /*发送一个时钟，判断器件是否正确应答 */
    {
        TP_I2C_Stop();
        return 1;
    }   
        
    TP_I2C_SendByte(reg >> 8);
    if (TP_I2C_WaitAck() != 0) 
    {
        TP_I2C_Stop();
        return 1;
    }  
  
    TP_I2C_SendByte(reg & 0xFF);
    if (TP_I2C_WaitAck() != 0) 
    {
        TP_I2C_Stop();
        return 1;
    }
  
    while(size)
    {       
        TP_I2C_SendByte(*buffer);
                      
        if (TP_I2C_WaitAck() != 0)
        {
            TP_I2C_Stop();
            return 1;
        }
      
        buffer++;	/* 地址增1 */	
        size--;      /*计数器自减 */         
    }
    
    TP_I2C_Stop();  /* 命令执行成功，发送I2C总线停止信号 */
    
    return 0;       
}


uint8_t Gt_Reg_Read(uint8_t addr,uint16_t reg,uint8_t *buffer,uint8_t size)
{   
    TP_I2C_Start();               /*发起I2C总线启动信号 */   
    TP_I2C_SendByte(GT_ADDR_WRITE(addr));  /*发送写设备地址 */ 
    if (TP_I2C_WaitAck() != 0)    /*发送一个时钟，判断器件是否正确应答 */
    {
        TP_I2C_Stop();
        return 1;
    }   
        
    TP_I2C_SendByte(reg >> 8);
    if (TP_I2C_WaitAck() != 0) 
    {
        TP_I2C_Stop();
        return 1;
    }  
  
    TP_I2C_SendByte(reg & 0xFF);
    if (TP_I2C_WaitAck() != 0) 
    {
        TP_I2C_Stop();
        return 1;
    }

    TP_I2C_Stop();
       
    TP_I2C_Start();               /*发起I2C总线启动信号 */   
    TP_I2C_SendByte(GT_ADDR_READ(addr));  /*发送写设备地址 */ 
    if (TP_I2C_WaitAck() != 0)    /*发送一个时钟，判断器件是否正确应答 */
    {
        TP_I2C_Stop();
        return 1;
    }       
               
    while(size > 1) 
    {
        *buffer = TP_I2C_ReadByte();                
        TP_I2C_Ack();   /* 中间字节读完后，CPU产生ACK信号(驱动SDA = 0) */                 
        buffer++;   /* 读指针自增 */  
        size--;  /*计数器自减 */         
    }

    if(size == 1)
    {
        *buffer = TP_I2C_ReadByte();     
        TP_I2C_NAck(); /* 最后1个字节读完后，CPU产生NACK信号(驱动SDA = 1) */   
    }    
      
    TP_I2C_Stop();  /* 发送I2C总线停止信号 */
    
    return 0;       
}


uint8_t Gt_Init(void)
{         
    uint8_t ret = 0;
         
    TP_I2C_Config();   /* 初始化TP、屏幕背板I2C总线,可拓展芯片 */
    
    Gt_Rest();         /* 硬件复位 */
    Gt_INT_ENABLE(0);  /* 默认不启用触摸中断 */

    for(int i = 0; i < 2; i++)
    {             
        if(Gt_Reg_Read(gt_addr_try[i],GT_REG_PRODUCT_ID,gt_id,GT_PRODUCT_ID_SIZE) == 0)             
        {                       
            gt_addr_use = gt_addr_try[i];  
            break;     
        }      
    }
      /* Test scan */
//    for(int i = 0; i < 255; i++)
//    {             
//        if(Gt_Reg_Read(i,GT_REG_PRODUCT_ID,gt_id,GT_PRODUCT_ID_SIZE) == 0)             
//        {                       
//            gt_addr_use = i;  
//            break;     
//        }      
//    }    
       
    if(gt_addr_use == 0)
    {
       ret = 1; /* Fail */
    }
           
    if(strstr((char*)gt_id,"911"))
    {
        gt_max_points = 5;
    }
    else if(strstr((char*)gt_id,"1151"))
    {
        gt_max_points = 10;      
    }
    else if(strstr((char*)gt_id,"917"))
    {
        gt_max_points = 5;      
    }
    else if(strstr((char*)gt_id,"5688"))
    {
        gt_max_points = 5;      
    }
    else
    {
       ret = 2; /* Fail */
    } 
    
    return ret;
}


void Gt_Rest(void)
{
    TP_Rest();     
}

void Gt_INT_ENABLE(uint8_t state)
{   
    TP_INT_ENABLE(state);     
}

uint8_t Gt_Get_Max_Points(void)
{
    return gt_max_points; 
}

void Gt_Get_ID_Temp(uint8_t* buffer)
{      
    memcpy(buffer,gt_id,GT_PRODUCT_ID_SIZE);
}


/* Return 3 when the controller has no new report; preserve caller state. */
uint8_t Gt_Get_Points_Data(GT_Reg_Point_t* points, int8_t* p_num)
{
    uint8_t status = 0, count, clear = 0, ret;
    ret = Gt_Reg_Read(gt_addr_use,GT_REG_STATUS,&status,1);
    if (ret) return ret;
    if (!GT_REG_STATUS_BUFFER(status)) return 3;
    count = GT_REG_STATUS_POINTS_NUM(status);
    if (count > gt_max_points || count > 5) {
        *p_num = 0;
        Gt_Reg_Write(gt_addr_use,GT_REG_STATUS,&clear,1);
        return 2;
    }
    if (count) {
        ret = Gt_Reg_Read(gt_addr_use,GT_REG_PONINTS,(uint8_t*)points,
                          (uint8_t)(sizeof(GT_Reg_Point_t)*count));
        if (ret) return ret;
    }
    ret = Gt_Reg_Write(gt_addr_use,GT_REG_STATUS,&clear,1);
    if (ret) return ret;
    *p_num = (int8_t)count;
    return 0;
}
